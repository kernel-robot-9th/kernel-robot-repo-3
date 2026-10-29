"""Overhead-camera waiting alignment; importing this module never starts motion."""
from copy import deepcopy
import json
import math
from pathlib import Path
import threading
import time

CONFIG = Path(__file__).resolve().parents[2]/'config/pinky-wait-parking.json'


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def load_config():
    return json.loads(CONFIG.read_text())


def relative(goal, current):
    dx, dy = goal['x']-current['x'], goal['y']-current['y']
    c, s = math.cos(current['yaw']), math.sin(current['yaw'])
    return c*dx+s*dy, -s*dx+c*dy, wrap(goal['yaw']-current['yaw'])


def transfer_goal(goal, camera_pose, odom_pose):
    x, y, yaw = relative(goal, camera_pose)
    c, s = math.cos(odom_pose['yaw']), math.sin(odom_pose['yaw'])
    return {'x':odom_pose['x']+c*x-s*y, 'y':odom_pose['y']+s*x+c*y,
            'yaw':wrap(odom_pose['yaw']+yaw)}


def footprint(config, scale=None):
    d = config['dimensions']; scale = config['basket_scale'] if scale is None else scale
    front, rear, half = d['body_front_m'], d['body_rear_m'], d['body_width_m']/2
    basket_half = d['basket_width_m']*scale/2
    back = d['basket_mount_x_m']-d['basket_length_m']*scale
    # Separate body and basket widths: scaling the basket must not shrink the robot.
    return [[front,-half],[front,half],[rear,half],[rear,basket_half],
            [back,basket_half],[back,-basket_half],[rear,-basket_half],[rear,-half]]


def to_layout(pose, transform):
    x,y,yaw = relative(pose,transform)
    return dict(x=x,y=y,yaw=yaw)


def prepare_targets(config):
    from .overhead import marker_pose
    from .wait_maneuvers import entry
    cam = json.loads(Path(config['camera_config']).read_text())
    calibration = json.loads(Path(cam['calibration_file']).read_text())
    transform = json.loads(Path(cam['layout_registry']).read_text())['layout_to_map']
    records = json.loads(Path(config['recorded_targets']).read_text())
    targets = {}
    for key, record in records.items():
        pose = marker_pose(record, calibration, cam['robots'][record['robot']])['base_pose']
        targets[key] = {'map_pose':pose, 'recorded_map_pose':dict(pose),
                        'recorded_at':record['recorded_at'], 'marker_id':record['marker_id']}
    for robot in cam['robots']:
        back,front = (targets[slot+'/'+robot]['map_pose'] for slot in ('back','front'))
        # Keep both taught centres and derive one shared straight heading.
        yaw = math.atan2(front['y']-back['y'],front['x']-back['x'])
        for slot in ('back','front'):
            target=targets[slot+'/'+robot];target['map_pose']['yaw']=yaw
            target['layout_pose']=to_layout(target['map_pose'],transform)
            target['approach'],_=entry(target['map_pose'],slot,config)
    return {'targets':targets, 'layout_to_map':transform, 'plane_height_m':calibration['plane_height_m'],
            'strategy':'rear_first_fixed_paths'}


def bezier(start, end, distance=.12):
    controls = [[start[0],start[1]], [start[0]+distance*math.cos(start[2]),start[1]+distance*math.sin(start[2])],
                [end[0]-distance*math.cos(end[2]),end[1]-distance*math.sin(end[2])],end[:2]]
    count = max(2, math.ceil(sum(math.dist(a,b) for a,b in zip(controls,controls[1:]))/.005))
    poses=[]
    for i in range(count+1):
        t=i/count;weights=[(1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3]
        xy=[sum(w*p[j] for w,p in zip(weights,controls)) for j in range(2)]
        d=[sum(w*(b[j]-a[j]) for w,a,b in zip([(1-t)**2,2*(1-t)*t,t*t],controls,controls[1:])) for j in range(2)]
        poses.append(xy+[math.atan2(d[1],d[0])])
    poses[-1]=end[:]
    return poses


def waiting_route(plan, robot, prepared):
    """Register rear entry, front reverse entry and straight queue advance."""
    from .wait_maneuvers import entry, queue_segment
    plan=deepcopy(plan); route=plan['route_id']; targets=prepared['targets']
    if route.startswith('handoff_to_home_'):
        slot=route.removeprefix('handoff_to_home_')
        stage,parking=entry(targets[slot+'/'+robot]['map_pose'],slot,load_config())
        segments=plan['segments']
        west=next((i for i,s in enumerate(segments) if s['name']=='return_west'),None)
        if west is None:
            west=max(i for i,s in enumerate(segments) if s['name']=='road')
        poses=segments[west]['poses']; xy=[stage['x'],stage['y']]
        closest=min(range(1,len(poses)),key=lambda i:math.dist(poses[i][:2],xy))
        cut=closest
        remaining=0.
        while cut>1 and remaining<.20:
            remaining+=math.dist(poses[cut][:2],poses[cut-1][:2]);cut-=1
        segments[west]['poses']=poses[:cut+1]
        end=[*xy,poses[cut][2]]
        if math.dist(poses[cut][:2],xy)>.001:
            segments[west]['poses']+=bezier(poses[cut],end,.07)[1:]
        segments=segments[:west+1]
        segments[-1]['goal_checker_id']='observation_goal_checker'
        segments+=parking
        plan.update(segments=segments,waiting_slot=slot)
    elif route=='queue_advance':
        start=targets['back/'+robot]['map_pose'];end=targets['front/'+robot]['map_pose']
        plan['segments']=[queue_segment(start,end)]
        plan['waiting_slot']='front'
    elif route.startswith('home_to_'):
        start=targets['front/'+robot]['map_pose']
        if plan.get('route_version') == 3:
            poses=plan['segments'][0]['poses'];origin=poses[0]
            dx,dy,da=start['x']-origin[0],start['y']-origin[1],wrap(start['yaw']-origin[2])
            plan['segments'][0]['poses']=[[x+dx*(1-i/(len(poses)-1)),y+dy*(1-i/(len(poses)-1)),
                wrap(a+da*(1-i/(len(poses)-1)))] for i,(x,y,a) in enumerate(poses)]
            return plan
        # Drive forward and bend into the open aisle before the existing departure rotation.
        c,s=math.cos(start['yaw']),math.sin(start['yaw'])
        exit_pose=[start['x']+.45*c-.18*s,start['y']+.45*s+.18*c,start['yaw']]
        plan['segments'].insert(0,{'name':'waiting_departure','direction':1,
                                  'poses':bezier([start[k] for k in ('x','y','yaw')],exit_pose),
                                  'goal_checker_id':'observation_goal_checker'})
    return plan


def align_wait(robot, slot, profile, cancelled=None, *, segments):
    from .aruco_parking import ParkingDrive
    from .camera_navigation import observation
    from .pinky import atomic_json
    from .wait_maneuvers import PathController
    cfg=load_config()
    cancelled=cancelled or threading.Event();controller=PathController(segments,cfg)
    directory=Path(cfg['runs_directory'])/(str(time.time_ns())+'-'+robot+'-'+slot);directory.mkdir(parents=True)
    atomic_json(directory/'plan.json',{'segments':segments,'real_footprint':footprint(cfg,1.)})
    drive=ParkingDrive(profile,cancelled); camera_reference=odom_reference=None; last_log=0.; last_phase=None
    status_path=Path(cfg['targets_file']).parent/(robot+'-status.json')
    print(robot+' 전체 카메라 대기 정렬: '+slot+' (3cm·7°)',flush=True)
    try:
        with (directory/'events.jsonl').open('w',buffering=1) as log:
            while not cancelled.is_set():
                obs=observation(profile['camera_socket']);seen=obs.get('robots',{}).get(profile['robot_id'],{})
                odom=drive.snapshot()
                if odom and obs.get('running') and seen.get('visible') and seen.get('map_pose'):
                    camera_reference,odom_reference=seen['map_pose'],odom['pose']
                if not odom or camera_reference is None:
                    drive.move(); state={'phase':'waiting_for_camera_and_odom'}
                else:
                    current=transfer_goal(odom['pose'],odom_reference,camera_reference)
                    state=controller.step(current)
                    state['pose']=current
                    # Only a visible camera observation confirms final alignment.
                    if state['phase'] in ('aligned','advanced') and not seen.get('visible'):
                        state['phase']='waiting_for_camera_confirmation'
                    drive.move(state['linear'],state['angular'])
                state.update(robot=robot,slot=slot,at=time.time(),marker_visible=bool(seen.get('visible')))
                if state['phase']!=last_phase:
                    print('대기 정렬:',state['phase'],flush=True);last_phase=state['phase']
                if time.monotonic()-last_log>.2:
                    log.write(json.dumps(state)+'\n');atomic_json(status_path,state);last_log=time.monotonic()
                if state['phase'] in ('aligned','advanced'):
                    result={**state,'status':state['phase'],'record':str(directory)}
                    atomic_json(directory/'result.json',result);atomic_json(status_path,result);return result
                cancelled.wait(.05)
        raise RuntimeError('대기 정렬 취소')
    finally:
        drive.close()


def camera_view(value):
    cfg=load_config();path=Path(cfg['targets_file'])
    value=dict(value,dimensions=cfg['dimensions'],basket_scale=cfg['basket_scale'],
               planning_footprint=footprint(cfg),wait_tolerance={'position_m':cfg['position_tolerance_m'],'yaw_deg':cfg['yaw_tolerance_deg']})
    if path.exists():
        prepared=json.loads(path.read_text());value['waiting_targets']=prepared['targets']
        for name in ('P1','P2'):
            status=path.parent/(name+'-status.json')
            if status.exists():value.setdefault('waiting_status',{})[name]=json.loads(status.read_text())
    from .station_remote import configuration
    try:
        profiles=configuration()['profiles']
        value['applied']={}
        for robot, filename in profiles.items():
            profile=json.loads(Path(filename).read_text())
            value['applied'][robot]={'waiting':bool(profile.get('wait_targets_file')),
                                     'basket_scale':profile.get('planning_basket_scale')}
    except FileNotFoundError:
        pass
    return value
