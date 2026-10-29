"""Plot prepared waiting paths and real basket envelopes; never opens ROS/camera."""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from robot_gateway.hardware.wait_parking import load_config, to_layout
from robot_gateway.hardware.wait_maneuvers import entry, envelope, queue_segment, values


def overlap(a,b):
    area,_=cv2.intersectConvexConvex(cv2.convexHull(np.float32(a)),cv2.convexHull(np.float32(b)))
    return float(area)


def report(targets,config):
    from robots.pinky import compact
    width,depth=(compact.bundle()[0][k] for k in ('width','depth'))
    def layout(p):
        return to_layout(dict(zip(('x','y','yaw'),p)),targets['layout_to_map'])
    rows=[]
    for robot in ('P1','P2'):
        other='P2' if robot=='P1' else 'P1'
        for slot in ('back','front','advance'):
            back,front=(targets['targets'][s+'/'+robot]['map_pose'] for s in ('back','front'))
            if slot=='advance':
                segments=[queue_segment(back,front)];occupied=None
            else:
                stage,segments=entry(targets['targets'][slot+'/'+robot]['map_pose'],slot,config)
                occupied=targets['targets'][('front' if slot=='back' else 'back')+'/'+other]['map_pose']
            poses=[p for seg in segments for p in seg['poses']]
            # Include the complete turn envelope, not just its final heading.
            if slot!='advance':
                poses += [[stage['x'],stage['y'],i*math.pi/90] for i in range(180)]
            minimum=math.inf;area=0.
            obstacle=envelope(occupied,config) if occupied else None
            for p in poses:
                body=envelope(dict(zip(('x','y','yaw'),p)),config)
                for x,y in body:
                    v=layout([x,y,0.]);minimum=min(minimum,v['x'],width-v['x'],v['y']+depth,-v['y'])
                if obstacle:area=max(area,overlap(body,obstacle))
            rows.append(dict(robot=robot,maneuver=slot,minimum_model_wall_gap_m=minimum,
                             maximum_other_robot_overlap_m2=area,segments=segments,occupied=occupied))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--targets',default='runtime/field/pinky-route-modes/wait-targets.json')
    p.add_argument('--output',default='runtime/field/pinky-wait-parking/rear-first-preview.png')
    args=p.parse_args();cfg=load_config();data=json.loads(Path(args.targets).read_text())
    rows=report(data,cfg)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    fig,axes=plt.subplots(2,3,figsize=(13,7),layout='constrained')
    transform=data['layout_to_map']
    def layout(points):
        return [[v['x'],v['y']] for v in [to_layout(dict(x=x,y=y,yaw=0.),transform) for x,y in points]]
    for ax,row in zip(axes.flat,rows):
        ax.plot([0,2,2,0,0],[0,0,-1.5,-1.5,0],color='black')
        for name in ('back','front'):
            goal=data['targets'][name+'/'+row['robot']]['map_pose'];point=layout([values(goal)[:2]])[0]
            ax.scatter(*point,color='black',s=15);ax.annotate(name,point,xytext=(0,8),textcoords='offset points')
        if row['occupied']:
            ax.add_patch(Polygon(layout(envelope(row['occupied'],cfg)),color='tomato',alpha=.55))
        for seg in row['segments']:
            points=np.array(layout([v[:2] for v in seg['poses']]))
            ax.plot(points[:,0],points[:,1],color='teal' if seg['direction']>=0 else 'purple',linewidth=2)
            for pose in seg['poses'][::max(1,len(seg['poses'])//12)]:
                ax.add_patch(Polygon(layout(envelope(dict(zip(('x','y','yaw'),pose)),cfg)),
                                     fill=False,edgecolor='steelblue',alpha=.3))
            if seg['direction']==0:
                a=seg['poses'][0]
                for yaw in np.linspace(0,2*math.pi,12):
                    ax.add_patch(Polygon(layout(envelope(dict(x=a[0],y=a[1],yaw=yaw),cfg)),
                                         fill=False,edgecolor='orange',alpha=.15))
        ax.set(xlim=(-.03,2.03),ylim=(-1.53,-.7),aspect='equal',
               title=f"{row['robot']} {row['maneuver']} | model gap {row['minimum_model_wall_gap_m']*100:.1f} cm")
        ax.grid(alpha=.2)
    fig.suptitle('Prepared paths / REAL basket envelope / red: occupied robot / model only, not field verified')
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=160);plt.close(fig)
    summary=[{k:v for k,v in row.items() if k not in ('segments','occupied')} for row in rows]
    output.with_suffix('.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(dict(preview=str(output),checks=summary),ensure_ascii=False))


if __name__=='__main__':main()
