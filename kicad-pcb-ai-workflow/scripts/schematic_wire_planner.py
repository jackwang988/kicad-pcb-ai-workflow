"""Bounded orthogonal pre-routing on declared geometry; not a KiCad writer."""
import heapq
from schematic_space_map import corridor, point
from schematic_geometry import intersects


def clear_segment(a,b,obstacles,width,dimensions):
    if not (0<=a[0]<=dimensions[0] and 0<=b[0]<=dimensions[0] and
            0<=a[1]<=dimensions[1] and 0<=b[1]<=dimensions[1]):
        return False
    box=corridor(a,b,width/2)
    if box[0]<0 or box[1]<0 or box[2]>dimensions[0] or box[3]>dimensions[1]:
        return False
    return not any(intersects(box,block) for _,block in obstacles)


def route(a,b,obstacles,step,width,dimensions,max_nodes=12000):
    """Deterministic A* over a grid enriched with exact start/end coordinates.

    Not a guaranteed-complete continuous-plane router. Failure is a hard stop
    for this candidate, not a proof that no possible placement exists.
    """
    a=point(list(a));b=point(list(b))
    if a==b:return [a]
    if step<0.5:raise ValueError('Routing grid too small')
    xs=sorted(set(round(i*step,5) for i in range(int(dimensions[0]/step)+1)) | {round(a[0],5),round(b[0],5)})
    ys=sorted(set(round(i*step,5) for i in range(int(dimensions[1]/step)+1)) | {round(a[1],5),round(b[1],5)})
    if len(xs)*len(ys)>50000:raise ValueError('Route grid exceeds bounded preflight limits')
    xindex={x:i for i,x in enumerate(xs)};yindex={y:i for i,y in enumerate(ys)}
    start=(xindex[round(a[0],5)],yindex[round(a[1],5)])
    finish=(xindex[round(b[0],5)],yindex[round(b[1],5)])
    h=lambda p:abs(xs[p[0]]-b[0])+abs(ys[p[1]]-b[1])
    queue=[(h(start),0,start)];seen={start:0};parents={};count=0
    while queue:
        _,cost,node=heapq.heappop(queue)
        if cost!=seen.get(node):continue
        count+=1
        if count>max_nodes:raise ValueError('Routing search node budget exceeded')
        if node==finish:
            vertices=[node]
            while node in parents:
                node=parents[node];vertices.append(node)
            vertices.reverse()
            pts=[(xs[x],ys[y]) for x,y in vertices]
            corners=[pts[0]]
            for i in range(1,len(pts)-1):
                if (pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])!= (pts[i+1][0]-pts[i][0],pts[i+1][1]-pts[i][1]):
                    # Different step lengths are still the same direction.
                    if (pts[i][0]==pts[i-1][0]) != (pts[i+1][0]==pts[i][0]):corners.append(pts[i])
            corners.append(pts[-1]);return corners
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            q=(node[0]+dx,node[1]+dy)
            if not(0<=q[0]<len(xs) and 0<=q[1]<len(ys)):continue
            pa=(xs[node[0]],ys[node[1]]);pb=(xs[q[0]],ys[q[1]])
            if not clear_segment(pa,pb,obstacles,width,dimensions):continue
            nc=cost+abs(pa[0]-pb[0])+abs(pa[1]-pb[1])
            if nc+1e-7<seen.get(q,float('inf')):
                seen[q]=nc;parents[q]=node;heapq.heappush(queue,(nc+h(q),nc,q))
    return None
