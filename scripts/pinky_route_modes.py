"""Build both replay versions into one graph per robot; no motion on prepare/apply."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from robot_gateway.hardware.pinky import atomic_json
from robot_gateway.hardware.station_remote import configuration, ssh
from robot_gateway.hardware.wait_parking import load_config, prepare_targets, waiting_route
from robots.pinky.field_routes import version_plan
from robots.pinky.route_graph import build_graph, observation_arrival

ROOT=Path('runtime/field/pinky-route-modes')


def prepare():
    cfg=load_config();ROOT.mkdir(parents=True,exist_ok=True)
    targets=prepare_targets(cfg);atomic_json(ROOT/'wait-targets.json',targets)
    control=configuration()
    for robot,file in control['profiles'].items():
        profile=json.loads(Path(file).read_text())
        old=json.loads(Path(profile['route_index_file']).read_text())['routes']
        names=list(dict.fromkeys(name.split('/')[-1] for name in old))
        observations=json.loads(Path(profile['observation_goals_file']).read_text());plans=[]
        for version in (3,4):
            for name in names:
                plan=version_plan(profile['goals_file'],name,version)
                zone={'A':'A','B':'B','handoff':'C'}.get(name.rsplit('_to_',1)[-1])
                if zone:
                    observation=dict(observations[zone+'/'+robot])
                    observation['goal_forward_m']+=profile.get('observation_extra_reverse_m',{}).get(zone,0.)
                    plan=observation_arrival(plan,observation)
                plan=waiting_route(plan,robot,targets)
                plan['route_id']=f'v{version}/{name}';plans.append(plan)
        graph,index=build_graph(plans)
        for name in names:index['routes'][name]=index['routes']['v4/'+name]
        graph_file=ROOT/(robot+'.geojson')
        atomic_json(graph_file,graph)
        index.update(graph_file=str(graph_file),route_modes=[3,4],
                     graph_sha256=hashlib.sha256(graph_file.read_bytes()).hexdigest())
        atomic_json(ROOT/(robot+'.json'),index)
        print(robot,'v3/v4 각각',len(names),'경로 준비. 노드 ID 분리, 대기 정렬 공통.')


def apply(robot):
    import paramiko,yaml
    control=configuration();cfg=load_config();profile_file=Path(control['profiles'][robot])
    profile=json.loads(profile_file.read_text());index=json.loads((ROOT/(robot+'.json')).read_text())
    graph_file=ROOT/(robot+'.geojson');data=graph_file.read_bytes()
    assert hashlib.sha256(data).hexdigest()==index['graph_sha256']
    backup=ROOT/('backup-'+robot+'-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    conn=paramiko.SSHClient();conn.load_system_host_keys();user,host=control['robots'][robot].split('@')
    conn.connect(host,username=user,key_filename=str(Path(control['ssh_key']).expanduser()),timeout=5)
    ftp=conn.open_sftp();remote='/home/pinky/cartrina-field/'
    try:
        with ftp.open(remote+'route_server.yaml') as f:settings=yaml.safe_load(f)
        destination=settings['route_server']['ros__parameters']['graph_filepath']
        with ftp.open(destination) as f:(backup/'remote.geojson').write_bytes(f.read())
        for path in [profile_file,Path(profile['route_index_file']),Path(profile['route_index_file']).with_suffix('.geojson')]:
            (backup/path.name).write_bytes(path.read_bytes())
        if Path(cfg['targets_file']).exists():
            (backup/'wait-targets.json').write_bytes(Path(cfg['targets_file']).read_bytes())
        with ftp.open(destination+'.new','wb') as f:f.write(data)
        ftp.posix_rename(destination+'.new',destination)
        ftp.put('scripts/run_pinky_route_server.sh',remote+'run_pinky_route_server.sh')
        command=f'PINKY_DOMAIN_ID={robot[-1]} bash ~/cartrina-field/run_pinky_route_server.sh reload'
        subprocess.run(ssh(control,control['robots'][robot],command),check=True)
        index['graph_file']=str(Path(profile['route_index_file']).with_suffix('.geojson'))
        Path(index['graph_file']).write_bytes(data);atomic_json(profile['route_index_file'],index)
        atomic_json(cfg['targets_file'],json.loads((ROOT/'wait-targets.json').read_text()))
        profile.update(route_modes=[3,4],wait_targets_file=cfg['targets_file']);atomic_json(profile_file,profile)
        print(robot,'v3/v4 그래프 적용. 이후 선택 시 재시작 불필요. 이동 명령 없음. 백업:',backup)
    finally:ftp.close();conn.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['prepare','apply'])
    p.add_argument('--robot',choices=['P1','P2']);args=p.parse_args()
    if args.operation=='prepare':prepare()
    elif not args.robot:p.error('apply에는 --robot 필요')
    else:apply(args.robot)
