"""Complete, directed reference paths in the layout frame.

These are piecewise SE(2) geometric references, not Nav2 routes or a hardware
controller. The final straight docking neck is shared under bay exclusivity.
"""
from dataclasses import dataclass
import math

from .geometry import dock_pose

ROUTE_VERSION = 3
LEFT, RIGHT = .38, 1.62
UPPER, LOWER = -.95, -1.19
CY, RADIUS = (UPPER+LOWER)/2, (UPPER-LOWER)/2
WIDTH = RIGHT - LEFT
LOOP_LENGTH = 2*WIDTH + 2*math.pi*RADIUS
STATIONS = ('A', 'B', 'handoff')
HOME_BACK, HOME_FRONT = (.46, -1.375, 0.0), (.80, -1.375, 0.0)


def angle_delta(a, b):
    return math.atan2(math.sin(b-a), math.cos(b-a))


def interpolate(a, b, t):
    return (a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t,
            a[2]+angle_delta(a[2], b[2])*t)


@dataclass
class Segment:
    name: str
    poses: list
    direction: int


def line(name, a, b, direction=1, step=.003):
    count = max(1, math.ceil(math.dist(a[:2], b[:2])/step))
    return Segment(name, [interpolate(a,b,i/count) for i in range(count+1)], direction)


def arc(name, cx, cy, radius, a0, a1, step=.003):
    count = max(1, math.ceil(abs(a1-a0)*radius/step), math.ceil(abs(a1-a0)/.01))
    sign = 1 if a1>a0 else -1
    poses=[]
    for i in range(count+1):
        a=a0+(a1-a0)*i/count
        poses.append((cx+radius*math.cos(a), cy+radius*math.sin(a), a+sign*math.pi/2))
    return Segment(name, poses, 1)


def bezier(name, control):
    # Dense construction also bounds the tangent changes used by the checker.
    poses=[]
    for i in range(401):
        t=i/400; s=1-t
        p=[s**3*control[0][j]+3*s*s*t*control[1][j]+3*s*t*t*control[2][j]+t**3*control[3][j] for j in (0,1)]
        d=[3*s*s*(control[1][j]-control[0][j])+6*s*t*(control[2][j]-control[1][j])+3*t*t*(control[3][j]-control[2][j]) for j in (0,1)]
        poses.append((*p,math.atan2(d[1],d[0])))
    return Segment(name,poses,1)


def loop_pose(distance):
    s=distance % LOOP_LENGTH
    if s <= WIDTH:
        return LEFT+s,CY-RADIUS,0.0
    s-=WIDTH
    if s <= math.pi*RADIUS:
        a=-math.pi/2+s/RADIUS
        return RIGHT+RADIUS*math.cos(a),CY+RADIUS*math.sin(a),a+math.pi/2
    s-=math.pi*RADIUS
    if s <= WIDTH:
        return RIGHT-s,CY+RADIUS,math.pi
    s-=WIDTH
    a=math.pi/2+s/RADIUS
    return LEFT+RADIUS*math.cos(a),CY+RADIUS*math.sin(a),a+math.pi/2


def loop_leg(start, end):
    length=(end-start) % LOOP_LENGTH
    # Include curvature transitions exactly, rather than cutting across them.
    cuts={0.0,length}
    for boundary in (0,WIDTH,WIDTH+math.pi*RADIUS,2*WIDTH+math.pi*RADIUS):
        d=(boundary-start) % LOOP_LENGTH
        if 0<d<length: cuts.add(d)
    poses=[]
    cuts=sorted(cuts)
    for a,b in zip(cuts,cuts[1:]):
        n=max(1,math.ceil((b-a)/.0015))
        poses.extend(loop_pose(start+a+(b-a)*i/n) for i in range(n))
    poses.append(loop_pose(end))
    return Segment('road',poses,1)


def station_paths(config, station):
    if station not in STATIONS: raise ValueError('Unknown station')
    index=STATIONS.index(station)
    dock=dock_pose(config,index)
    x=dock[0]
    north=(x,-.79,math.pi/2)
    south=(x,-.79,-math.pi/2)
    if station=='handoff':
        entry=bezier('entry',[(RIGHT+RADIUS,CY),(RIGHT+RADIUS,-.98),(1.6,-.93),(1.6,-.79)])
        entry_s=WIDTH+math.pi*RADIUS/2
    else:
        entry=arc('entry',x+.16,-.79,.16,-math.pi/2,-math.pi)
        entry_s=WIDTH+math.pi*RADIUS+RIGHT-(x+.16)
    if station=='A':
        exit_path=bezier('exit',[(.3,-.79),(.3,-.94),(LEFT-RADIUS,-.98),(LEFT-RADIUS,CY)])
        exit_s=2*WIDTH+1.5*math.pi*RADIUS
    else:
        exit_path=arc('exit',x-.16,-.79,.16,0,-math.pi/2)
        exit_s=WIDTH+math.pi*RADIUS+RIGHT-(x-.16)
    rotate=Segment('align_turn',[(x,-.79,math.pi/2+math.pi*i/360) for i in range(361)],0)
    return {'station':station,'entry_s':entry_s,'exit_s':exit_s,
            'entry':[entry,rotate,line('dock_reverse',south,dock,-1)],
            'exit':[line('dock_leave',dock,south),exit_path],
            'wait_pose':dock,'align_pose':north}


def join(segments):
    result=[]
    for segment in segments:
        if result:
            a,b=result[-1],segment.poses[0]
            if math.dist(a[:2],b[:2])>1e-8 or abs(angle_delta(a[2],b[2]))>1e-8:
                raise ValueError('Discontinuous segment: '+segment.name)
        result.extend(segment.poses if not result else segment.poses[1:])
    return result


def transfer(config, source, target):
    if source==target: raise ValueError('Transfer needs different stations')
    a,b=station_paths(config,source),station_paths(config,target)
    segments=a['exit']+[loop_leg(a['exit_s'],b['entry_s'])]+b['entry']
    join(segments)
    return segments


def home_paths():
    """FIFO queue: arrive from the west turn, advance east, merge gradually.

    Slots belong to queue positions, not permanent robot identities. The rear
    occupant cannot depart through an occupied front slot.
    """
    y=HOME_BACK[1]
    return_x=.45
    arrival=[arc('home_return',return_x,(UPPER+y)/2,(UPPER-y)/2,
                 math.pi/2,3*math.pi/2),
             line('home_park',(return_x,y,0),HOME_BACK)]
    advance=line('home_advance',HOME_BACK,HOME_FRONT)
    radius=.9
    angle=math.acos(1-(LOWER-y)/(2*radius))
    first=arc('home_depart',HOME_FRONT[0],y+radius,radius,
              -math.pi/2,-math.pi/2+angle)
    x,end_y,_=first.poses[-1]
    second=arc('home_merge',x+radius*math.sin(angle),end_y-radius*math.cos(angle),
               radius,math.pi/2+angle,math.pi/2)
    departure=[first,second]
    return {'back':HOME_BACK,'front':HOME_FRONT,'arrival':arrival,'advance':advance,
            'departure':departure,
            'entry_s':WIDTH+math.pi*RADIUS+RIGHT-return_x,
            'exit_s':second.poses[-1][0]-LEFT}


def home_to_station(config,station):
    home=home_paths(); target=station_paths(config,station)
    return home['departure']+[loop_leg(home['exit_s'],target['entry_s'])]+target['entry']


def station_to_home(config,station,slot='back'):
    if slot not in ('front','back'): raise ValueError('Unknown home slot')
    source=station_paths(config,station); home=home_paths()
    return (source['exit']+[loop_leg(source['exit_s'],home['entry_s'])]+home['arrival']
            +([home['advance']] if slot=='front' else []))
