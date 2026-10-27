"""Read-only overlay of pinned basket routes and the actual occupancy map."""
import argparse
import json
import math
from pathlib import Path
import time

from robot_gateway.hardware.pinky import PinkyMobile, atomic_json, load_profile, map_signature
from robots.pinky.field_routes import plan


def preview(profile_path, output, map_file=None, route_id='home_to_A'):
    import numpy as np
    from scipy.spatial import cKDTree
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    profile = load_profile(profile_path)
    selected = plan(profile['goals_file'], route_id)
    mobile = PinkyMobile(profile) if not map_file else None
    try:
        if map_file:
            import yaml
            from PIL import Image
            from types import SimpleNamespace as Obj
            path = Path(map_file)
            cfg = yaml.safe_load(path.read_text())
            pixels = np.array(Image.open(path.parent/cfg['image']).convert('L'))[::-1]
            occupied = pixels/255 if cfg.get('negate') else (255-pixels)/255
            cells = np.where(occupied>cfg['occupied_thresh'],100,np.where(occupied<cfg['free_thresh'],0,-1))
            origin=cfg['origin']
            message=Obj(info=Obj(width=pixels.shape[1],height=pixels.shape[0],
                resolution=float(np.float32(cfg['resolution'])),origin=Obj(
                position=Obj(x=float(origin[0]),y=float(origin[1]),z=0.0),
                orientation=Obj(x=0.0,y=0.0,z=math.sin(origin[2]/2),w=math.cos(origin[2]/2)))),
                data=cells.ravel().tolist())
            signature=map_signature(message)
        else:
            deadline = time.monotonic()+5
            while mobile.map is None and time.monotonic()<deadline:
                time.sleep(.1)
            with mobile.data_lock:
                message, signature = mobile.map, mobile.map_hash
        if message is None or signature != selected['map_sha256']:
            raise RuntimeError('등록한 실제 지도 수신 미확인')
        current = None
        if mobile:
            try:
                current=mobile.snapshot()
            except RuntimeError:
                pass
        info = message.info
        resolution = info.resolution
        ox, oy = info.origin.position.x, info.origin.position.y
        grid = np.array(message.data).reshape(info.height, info.width)
        rows, cols = np.where(grid != 0)
        obstacles = np.c_[ox+(cols+.5)*resolution, oy+(rows+.5)*resolution]
        tree = cKDTree(obstacles)
        box = np.array(selected['footprint'])
        # Include half a cell diagonal so intersected occupied cells are covered.
        margin = .01 + resolution/math.sqrt(2)
        rear, front = box[:,0].min()-margin, box[:,0].max()+margin
        half = max(abs(box[:,1]))+margin
        radius = max(math.hypot(rear,half), math.hypot(front,half))
        segments = selected['segments'][-1:] if profile.get('entry_planner_id') else selected['segments']
        poses = np.array([p for s in segments for p in s['poses']])
        conflicts = []
        for index,(x,y,yaw) in enumerate(poses):
            c,s = math.cos(yaw),math.sin(yaw)
            corners = np.array([[rear,-half],[front,-half],[front,half],[rear,half]]) @ np.array([[c,s],[-s,c]]) + [x,y]
            outside = bool(np.any(corners[:,0]<ox) or np.any(corners[:,0]>=ox+info.width*resolution)
                           or np.any(corners[:,1]<oy) or np.any(corners[:,1]>=oy+info.height*resolution))
            ids = tree.query_ball_point([x,y],radius)
            blocked = False
            if ids:
                d = obstacles[ids]-[x,y]
                local = d @ np.array([[c,-s],[s,c]])
                blocked = bool(np.any((local[:,0]>=rear)&(local[:,0]<=front)&(abs(local[:,1])<=half)))
            if outside or blocked:
                conflicts.append(index)
        start = poses[0]
        delta = (math.hypot(current['pose']['x']-start[0],current['pose']['y']-start[1]) if current else None)
        report = {'route_id':route_id,'source_hash':selected['source_hash'],
            'map_sha256':signature,'registration_sha256':selected['registration_sha256'],
            'transform_status':json.loads(Path(profile['goals_file']).read_text()).get(
                'registration_method', 'single_A_pose_candidate_unconfirmed'),
            'checked_segments':[s['name'] for s in segments],
            'adaptive_entry_requires_live_planner':bool(profile.get('entry_planner_id')),
            'basket_footprint':selected['footprint'],'checked_pose_count':len(poses),
            'conflicting_pose_count':len(conflicts),'map_sweep_clear':not conflicts,
            'start':start.tolist(),'end':poses[-1].tolist(),'current_pose':current['pose'] if current else None,
            'current_to_route_start_m':delta,'motion_executed':False,'physical_parking_verified':False}
        out = Path(output)
        atomic_json(out,report)
        atomic_json(out.with_name('pinky-p1-route-plan.json' if route_id == 'home_to_A'
                                 else f'pinky-{route_id}-route-plan.json'),selected)
        fig,ax=plt.subplots(figsize=(8,9))
        ax.imshow(np.where(grid<0,180,np.where(grid==0,245,25)),origin='lower',cmap='gray',vmin=0,vmax=255,
            extent=[ox,ox+info.width*resolution,oy,oy+info.height*resolution])
        for segment in segments:
            p=np.array(segment['poses']);color='#dd851b' if segment['direction']<0 else '#2975ba'
            ax.plot(p[:,0],p[:,1],color=color,lw=2,label=segment['name'])
        for index in range(0,len(poses),max(1,len(poses)//18)):
            x,y,yaw=poses[index];c,s=math.cos(yaw),math.sin(yaw)
            polygon=box @ np.array([[c,s],[-s,c]])+[x,y]
            polygon=np.r_[polygon,polygon[:1]];ax.plot(polygon[:,0],polygon[:,1],color='#777777',alpha=.5,lw=.7)
        if conflicts:
            p=poses[conflicts];ax.scatter(p[:,0],p[:,1],s=8,c='red',label='basket/map conflict')
        if current:
            p=current['pose'];ax.scatter([p['x']],[p['y']],c='#ed2e9c',s=70,label='P1 current')
        ax.scatter([start[0]],[start[1]],c='#28a545',s=70,label='route start')
        ax.scatter([poses[-1,0]],[poses[-1,1]],c='#144bb8',s=70,label='registered destination')
        ax.set(title=f'P1 / {route_id} / registered final docking path',xlabel='map x (m)',ylabel='map y (m)')
        ax.axis('equal');ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(out.with_suffix('.png'),dpi=130)
        plt.close(fig)
        print(json.dumps(report,ensure_ascii=False))
    finally:
        if mobile:
            mobile.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',default='runtime/field/pinky-mobile.json')
    parser.add_argument('--output',default='runtime/field/pinky-route-preview.json')
    parser.add_argument('--map',help='저장 지도 YAML. 지정하면 ROS/로봇 접속 없이 검사')
    parser.add_argument('--route', default='home_to_A', choices=['home_to_A', 'home_to_B', 'home_to_handoff'])
    args=parser.parse_args()
    preview(args.profile,args.output,args.map,args.route)
