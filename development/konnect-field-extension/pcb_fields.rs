//! Local, narrowly scoped field-only MCP extension for the LED repair.
//! No file fallback, pad/graphic edits, reference renaming or implicit retry.
use crate::mcp::protocol::CallToolResult;
use crate::tools::{get_path, with_board_ipc_classified, BoardAccess, ToolContext, ToolDef};
use crate::tool;
use anyhow::{bail, Context};
use konnect_ipc::{builders, gen::kiapi};
use prost::Message;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};

type Fp = kiapi::board::types::FootprintInstance;
type Field = kiapi::board::types::Field;

pub fn tool() -> ToolDef {
    tool!(
        "set_placed_footprint_fields",
        "Inspect or edit only placed footprint fields through live KiCad IPC. Board-space mm/degrees. Dry run by default; apply requires its exact plan_revision. Preserves all non-field protobuf content, uses one undo commit, and verifies fresh readback. Reference text cannot be renamed; no deletion or file fallback. Local open-source extension.",
        json!({"type":"object","additionalProperties":false,"properties":{
            "board":{"type":"string"},
            "updates":{"type":"array","minItems":1,"maxItems":100,"items":{"type":"object","additionalProperties":false,"properties":{
                "reference":{"type":"string"},
                "fields":{"type":"array","maxItems":16,"items":{"type":"object","additionalProperties":false,"properties":{
                    "name":{"type":"string"},"value":{"type":"string"},
                    "x":{"type":"number"},"y":{"type":"number"},"rotation":{"type":"number"},
                    "size":{"type":"number","minimum":0.8,"maximum":2.0},
                    "stroke":{"type":"number","minimum":0.12,"maximum":0.3},
                    "visible":{"type":"boolean"},"layer":{"type":"string","enum":["F.SilkS","F.Fab"]}
                },"required":["name"]}}
            },"required":["reference","fields"]}},
            "dry_run":{"type":"boolean","default":true},
            "expected_plan_revision":{"type":"string"}
        },"required":["board","updates"]}),
        |args,ctx| async move {handle(args,ctx).await}
    ).with_board_access(BoardAccess::LiveOnly)
}

fn reference(fp: &Fp) -> &str {
    fp.reference_field.as_ref().and_then(|f|f.text.as_ref()).and_then(|b|b.text.as_ref()).map(|t|t.text.as_str()).unwrap_or("")
}

fn protected(fp: &Fp) -> Vec<u8> {
    let mut p=fp.clone();
    p.reference_field=None; p.value_field=None;p.datasheet_field=None;p.description_field=None;
    if let Some(d)=p.definition.as_mut(){
        d.reference_field=None;d.value_field=None;d.datasheet_field=None;d.description_field=None;
        d.items.retain(|a|!builders::any_is(a,"kiapi.board.types.Field"));
    }
    p.encode_to_vec()
}

fn field_json(f: &Field) -> Value {
    let b=f.text.as_ref(); let t=b.and_then(|b|b.text.as_ref());let a=t.and_then(|t|t.attributes.as_ref());
    json!({"name":f.name,"id":f.id.as_ref().map(|i|i.id),"visible":f.visible,
        "uuid":b.and_then(|b|b.id.as_ref()).map(|i|i.value.as_str()),
        "value":t.map(|t|t.text.as_str()),"layer":b.map(|b|b.layer),
        "x":t.and_then(|t|t.position.as_ref()).map(|v|builders::nm_to_mm(v.x_nm)),
        "y":t.and_then(|t|t.position.as_ref()).map(|v|builders::nm_to_mm(v.y_nm)),
        "rotation":a.and_then(|a|a.angle.as_ref()).map(|v|v.value_degrees),
        "size":a.and_then(|a|a.size.as_ref()).map(|v|[builders::nm_to_mm(v.x_nm),builders::nm_to_mm(v.y_nm)]),
        "stroke":a.and_then(|a|a.stroke_width.as_ref()).map(|v|builders::nm_to_mm(v.value_nm))})
}

fn all_fields(fp: &Fp) -> anyhow::Result<Vec<Field>> {
    let mut f=vec![];
    for v in [&fp.reference_field,&fp.value_field,&fp.datasheet_field,&fp.description_field].into_iter().flatten(){f.push(v.clone());}
    if let Some(d)=&fp.definition {for a in &d.items {if builders::any_is(a,"kiapi.board.types.Field"){f.push(Field::decode(a.value.as_slice())?);}}}
    Ok(f)
}

fn patch_field(f: &mut Field, patch: &Value) -> anyhow::Result<()> {
    if let Some(v)=patch.get("value") {
        let v=v.as_str().context("value must be text")?;
        if matches!(f.name.as_str(),"Reference"|"Value") {bail!("Reference and value content changes refused");}
        f.text.as_mut().context("field lacks BoardText")?.text.as_mut().context("field lacks Text")?.text=v.to_string();
    }
    if let Some(v)=patch.get("visible"){f.visible=v.as_bool().context("visible must be boolean")?;}
    let b=f.text.as_mut().context("field lacks BoardText")?;
    if let Some(v)=patch.get("layer") {
        let v=v.as_str().context("layer must be text")?;
        if !matches!(v,"F.SilkS"|"F.Fab"){bail!("Only front silk/fab field layers supported");}
        b.layer=builders::try_layer_from_name(v)? as i32;
    }
    let t=b.text.as_mut().context("field lacks Text")?;
    for (key,xaxis) in [("x",true),("y",false)] {
        if let Some(v)=patch.get(key){
            let n=v.as_f64().filter(|n|n.is_finite() && n.abs()<10000.).context("invalid coordinate")?;
            let p=t.position.as_mut().context("field lacks position")?;
            if xaxis{p.x_nm=builders::mm_to_nm(n);}else{p.y_nm=builders::mm_to_nm(n);}
        }
    }
    let a=t.attributes.as_mut().context("field lacks attributes")?;
    if let Some(v)=patch.get("rotation"){
        let n=v.as_f64().filter(|n|n.is_finite()&&n.abs()<=360.).context("invalid rotation")?;
        a.angle=Some(kiapi::common::types::Angle{value_degrees:n});
    }
    if let Some(v)=patch.get("size"){
        let n=v.as_f64().filter(|n|(0.8..=2.).contains(n)).context("size outside supported range")?;
        a.size=Some(builders::vec2(n,n));
    }
    if let Some(v)=patch.get("stroke"){
        let n=v.as_f64().filter(|n|(0.12..=0.3).contains(n)).context("stroke outside supported range")?;
        a.stroke_width=Some(builders::distance(n));
    }
    Ok(())
}

fn patch(fp:&Fp, patches:&[Value])->anyhow::Result<Fp>{
    let mut out=fp.clone();let mut names=HashSet::new();
    for p in patches {
        let name=p["name"].as_str().filter(|s|!s.is_empty()&&s.len()<100).context("invalid field name")?;
        if !names.insert(name.to_string()){bail!("duplicate field name");}
        match name {
            "Reference"=>patch_field(out.reference_field.as_mut().context("missing Reference")?,p)?,
            "Value"=>patch_field(out.value_field.as_mut().context("missing Value")?,p)?,
            "Datasheet"=>patch_field(out.datasheet_field.as_mut().context("missing Datasheet")?,p)?,
            "Description"=>patch_field(out.description_field.as_mut().context("missing Description")?,p)?,
            _=>{
                let mut existing=vec![];
                for (i,a) in out.definition.as_ref().context("no definition")?.items.iter().enumerate(){
                    if builders::any_is(a,"kiapi.board.types.Field") {
                        let f=Field::decode(a.value.as_slice())?;if f.name==name{existing.push((i,f));}
                    }
                }
                if existing.len()>1{bail!("ambiguous custom field");}
                let (index,mut field)=if let Some((i,f))=existing.pop(){(Some(i),f)}else{
                    if p.get("value").and_then(Value::as_str).is_none(){bail!("new custom field needs value");}
                    let next=all_fields(&out)?.iter().filter_map(|f|f.id.as_ref().map(|i|i.id)).max().unwrap_or(3).max(3)+1;
                    let mut f=out.reference_field.clone().context("no Reference template")?;
                    f.id=Some(kiapi::board::types::FieldId{id:next});f.name=name.to_string();f.visible=false;
                    let b=f.text.as_mut().context("template lacks BoardText")?;
                    b.id=Some(kiapi::common::types::Kiid{value:uuid::Uuid::new_v4().to_string()});
                    b.layer=builders::try_layer_from_name("F.Fab")? as i32;
                    (None,f)
                };
                patch_field(&mut field,p)?;
                let packed=builders::pack_any(&field,"kiapi.board.types.Field");
                let d=out.definition.as_mut().context("no definition")?;
                if let Some(i)=index{d.items[i]=packed;}else{d.items.push(packed);}
            }
        }
    }
    if protected(fp)!=protected(&out){bail!("field edit changed protected footprint data");}
    Ok(out)
}

fn read_footprints(c:&konnect_ipc::client::KiCadIpcClient)->anyhow::Result<BTreeMap<String,Fp>>{
    let mut found=BTreeMap::new();
    for a in c.get_items(kiapi::common::types::KiCadObjectType::KotPcbFootprint)?{
        if builders::any_is(&a,"kiapi.board.types.FootprintInstance"){
            let fp=Fp::decode(a.value.as_slice())?;let r=reference(&fp).to_string();
            if found.insert(r.clone(),fp).is_some(){bail!("Ambiguous reference {r}");}
        }
    }
    Ok(found)
}

async fn handle(args:&Value,ctx:&ToolContext)->anyhow::Result<CallToolResult>{
    let board=get_path(args,"board")?;let request=args.clone();
    let result=with_board_ipc_classified(ctx,&board,move|c,_|{
        let updates=request["updates"].as_array().filter(|v|!v.is_empty()&&v.len()<=100).context("invalid updates")?;
        let before=read_footprints(c)?;let mut changes=BTreeMap::new();let mut hash=Sha256::new();
        hash.update(serde_json::to_vec(updates)?);
        for u in updates {
            let r=u["reference"].as_str().context("missing reference")?;
            let fp=before.get(r).with_context(||format!("missing footprint {r}"))?;
            let fields=u["fields"].as_array().filter(|v|v.len()<=16).context("invalid fields")?;
            hash.update(fp.encode_to_vec());
            let after=patch(fp,fields)?;
            if changes.insert(r.to_string(),after).is_some(){bail!("duplicate reference");}
        }
        let revision=format!("{:x}",hash.finalize());
        let plans=changes.iter().map(|(r,a)|Ok(json!({"reference":r,"before":all_fields(&before[r])?.iter().map(field_json).collect::<Vec<_>>(),"after":all_fields(a)?.iter().map(field_json).collect::<Vec<_>>()}))).collect::<anyhow::Result<Vec<_>>>()?;
        if request["dry_run"].as_bool().unwrap_or(true){return Ok(json!({"status":"planned","plan_revision":revision,"plans":plans}));}
        if request["expected_plan_revision"].as_str()!=Some(&revision){bail!("stale or missing expected_plan_revision; nothing written");}
        let changed=changes.iter().filter(|(r,a)|**a!=before[*r]).map(|(_,a)|builders::pack_any(a,"kiapi.board.types.FootprintInstance")).collect::<Vec<_>>();
        if changed.is_empty(){return Ok(json!({"status":"unchanged","plan_revision":revision,"plans":plans}));}
        c.run_commit("Repair placed footprint fields (MCP)",|c|c.update_items(changed))?;
        let observed=read_footprints(c)?;
        for (r,want) in &changes {
            let got=observed.get(r).context("post-update footprint missing; uncertain")?;
            if protected(&before[r])!=protected(got){bail!("UNCERTAIN: protected footprint content changed on {r}; inspect before continuing");}
            let wanted=all_fields(want)?.iter().map(field_json).collect::<Vec<_>>();
            let actual=all_fields(got)?.iter().map(field_json).collect::<Vec<_>>();
            if wanted!=actual{bail!("UNCERTAIN: field readback differs on {r}; inspect before continuing. wanted={wanted:?},actual={actual:?}");}
        }
        Ok(json!({"status":"applied_verified","plan_revision":revision,"footprints":changes.len(),"plans":plans,"source":"ipc"}))
    }).await?;
    match result {Ok(v)=>Ok(CallToolResult::json(&v)),Err(e)=>Ok(CallToolResult::error(format!("{e:?}")))}
}

#[cfg(test)] mod tests {
    use super::*;
    fn fixture()->Fp {
        Fp{reference_field:Some(Field{name:"Reference".into(),text:Some(kiapi::board::types::BoardText{text:Some(kiapi::common::types::Text{position:Some(builders::vec2(10.,20.)),attributes:Some(kiapi::common::types::TextAttributes::default()),text:"D1".into(),..Default::default()}),..Default::default()}),..Default::default()}),definition:Some(kiapi::board::types::Footprint::default()),..Default::default()}
    }
    #[test] fn edits_only_fields(){let p=fixture();let q=patch(&p,&[json!({"name":"Reference","x":12.,"y":22.,"rotation":0.,"size":0.8,"stroke":0.12}),json!({"name":"MPN","value":"150283RS73103","visible":false})]).unwrap();assert_eq!(protected(&p),protected(&q));assert_eq!(reference(&q),"D1");assert_eq!(all_fields(&q).unwrap().len(),2);}
    #[test] fn refuses_reference_rename_and_undersized_text(){assert!(patch(&fixture(),&[json!({"name":"Reference","value":"X1"})]).is_err());assert!(patch(&fixture(),&[json!({"name":"Reference","size":0.1})]).is_err());}
    #[test] fn detects_non_field_changes(){let p=fixture();let mut q=p.clone();q.layer=99;assert_ne!(protected(&p),protected(&q));}
}
