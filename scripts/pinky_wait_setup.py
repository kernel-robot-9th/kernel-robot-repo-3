"""Prepare waiting routes offline; apply route or footprint settings only on request."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from robot_gateway.hardware.station_remote import configuration, ssh
from robot_gateway.hardware.wait_parking import load_config, prepare_targets, footprint
from robot_gateway.hardware.pinky import atomic_json

ROOT=Path('runtime/field/pinky-wait-parking')


def prepare():
    cfg=load_config();ROOT.mkdir(parents=True,exist_ok=True)
    atomic_json(cfg['targets_file'],prepare_targets(cfg))
    control=configuration()
    for robot,filename in control['profiles'].items():
        profile=json.loads(Path(filename).read_text())
        original=json.loads(Path(profile['route_index_file']).read_text())
        profile['wait_targets_file']=cfg['targets_file']
        staged=ROOT/(robot+'-profile.json');atomic_json(staged,profile)
        subprocess.run([sys.executable,'-m','scripts.pinky_export_routes','--profile',str(staged),
                        '--network','--routes',*original['routes'],'--output',str(ROOT/(robot+'-routes.json'))],check=True)
    atomic_json(ROOT/'basket-footprint.json',{'scale':cfg['basket_scale'],'footprint':footprint(cfg),
        'dimensions':cfg['dimensions']})
    print('대기 정렬 3cm·7°, 바구니 70% 준비 완료. 로봇 설정·주행은 변경하지 않았습니다.')


def apply(robot, stage):
    import paramiko
    import yaml
    cfg=load_config();control=configuration();profile_path=Path(control['profiles'][robot])
    profile=json.loads(profile_path.read_text()); user,host=control['robots'][robot].split('@')
    client=paramiko.SSHClient();client.load_system_host_keys()
    client.connect(host,username=user,key_filename=str(Path(control['ssh_key']).expanduser()),timeout=5)
    ftp=client.open_sftp();remote='/home/pinky/cartrina-field/';stamp=time.strftime('%Y%m%d-%H%M%S')
    backup=ROOT/('backup-'+robot+'-'+stamp);backup.mkdir(parents=True)
    try:
        if stage=='waiting':
            index=json.loads((ROOT/(robot+'-routes.json')).read_text())
            graph=(ROOT/(robot+'-routes.geojson')).read_bytes()
            with ftp.open(remote+'route_server.yaml') as stream: settings=yaml.safe_load(stream)
            destination=settings['route_server']['ros__parameters']['graph_filepath']
            with ftp.open(destination) as stream:(backup/'remote-graph.geojson').write_bytes(stream.read())
            with ftp.open(destination+'.new','wb') as stream:stream.write(graph)
            ftp.posix_rename(destination+'.new',destination)
            ftp.put('scripts/run_pinky_route_server.sh',remote+'run_pinky_route_server.sh')
            for path in [profile_path,Path(profile['route_index_file']),Path(profile['route_index_file']).with_suffix('.geojson')]:
                (backup/path.name).write_bytes(path.read_bytes())
            index['graph_file']=str(Path(profile['route_index_file']).with_suffix('.geojson'))
            atomic_json(profile['route_index_file'],index);Path(index['graph_file']).write_bytes(graph)
            profile['wait_targets_file']=cfg['targets_file'];atomic_json(profile_path,profile)
            command=f'PINKY_DOMAIN_ID={robot[-1]} bash ~/cartrina-field/run_pinky_route_server.sh reload'
        else:
            (backup/profile_path.name).write_bytes(profile_path.read_bytes())
            path=remote+'nav2_basket.yaml'
            with ftp.open(path) as stream:data=stream.read()
            (backup/'nav2_basket.yaml').write_bytes(data)
            settings=yaml.safe_load(data)
            for name in ('local_costmap','global_costmap'):
                params=settings[name][name]['ros__parameters']
                params['footprint']=json.dumps(footprint(cfg));params['footprint_padding']=0.0
            settings['controller_server']['ros__parameters']['FollowPath']['use_collision_detection']=True
            with ftp.open(path+'.new','w') as stream:stream.write(yaml.safe_dump(settings,sort_keys=False))
            ftp.posix_rename(path+'.new',path)
            ftp.put('scripts/run_pinky_robot.sh',remote+'run_pinky_robot.sh')
            command=f'PINKY_DOMAIN_ID={robot[-1]} PINKY_ROBOT_ID=pinky-{robot[-1]} bash ~/cartrina-field/run_pinky_robot.sh navigation'
        subprocess.run(ssh(control,control['robots'][robot],command),check=True)
        if stage=='basket':
            profile['planning_footprint']=footprint(cfg);profile['planning_basket_scale']=cfg['basket_scale']
            atomic_json(profile_path,profile)
        print(robot,stage,'적용 완료. 이동 명령 없음. 백업:',backup)
    finally:
        ftp.close();client.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['prepare','apply']);p.add_argument('--robot',choices=['P1','P2'])
    p.add_argument('--stage',choices=['waiting','basket'],default='waiting');args=p.parse_args()
    if args.operation=='prepare':prepare()
    elif not args.robot:p.error('apply에는 --robot 필요')
    else:apply(args.robot,args.stage)
