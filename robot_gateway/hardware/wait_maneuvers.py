"""Fixed waiting manoeuvres; geometry and tracking without ROS side effects."""
import math

from .wait_parking import bezier, footprint, relative, wrap


def offset(pose, forward=0., left=0., turn=0.):
    c, s = math.cos(pose['yaw']), math.sin(pose['yaw'])
    return dict(x=pose['x']+c*forward-s*left,
                y=pose['y']+s*forward+c*left, yaw=wrap(pose['yaw']+turn))


def values(pose):
    return [pose[k] for k in ('x', 'y', 'yaw')]


def envelope(pose, config):
    c,s = math.cos(pose['yaw']),math.sin(pose['yaw'])
    return [[pose['x']+c*x-s*y,pose['y']+s*x+c*y] for x,y in footprint(config,1.)]


def straight(start, end):
    count = max(1, math.ceil(math.dist(values(start)[:2], values(end)[:2])/.005))
    return [[start[k]+(end[k]-start[k])*i/count for k in ('x', 'y', 'yaw')]
            for i in range(count+1)]


def entry(target, slot, config):
    """Turn in the open end space; approach back forward, front in reverse."""
    direction = 1 if slot == 'back' else -1
    length = config['entry_length_m'] if slot == 'back' else config['front_entry_length_m']
    handle = config['entry_handle_m'] if slot == 'back' else config['front_entry_handle_m']
    stage = offset(target, -direction*length,
                   config['entry_inboard_m'], -direction*math.pi/2)
    end = offset(target, -direction*config['final_straight_m'])
    a, b = values(stage), values(end)
    if direction < 0:
        a[2] = wrap(a[2]+math.pi); b[2] = wrap(b[2]+math.pi)
    curve = bezier(a, b, handle)
    if direction < 0:
        curve = [[x,y,wrap(yaw+math.pi)] for x,y,yaw in curve]
    common = dict(camera_guided=True, waiting_slot=slot)
    segments = [dict(common, name='waiting_open_turn', direction=0, poses=[values(stage)]),
                dict(common, name='waiting_'+slot+'_curve', direction=direction, poses=curve),
                dict(common, name='waiting_'+slot+'_straight', direction=direction,
                     straight=True, poses=straight(end,target))]
    return stage, segments


def queue_segment(back, front):
    return dict(name='queue_straight', direction=1, poses=straight(back,front),
                camera_guided=True, straight=True, advance_only=True, waiting_slot='front')


def return_routes(other_location, destination=None):
    """Only direct-front park when the rear slot is occupied; never move its occupant."""
    destination = destination or ('back' if other_location == 'front' else 'front')
    if destination == 'back':
        return destination, ['handoff_to_home_back']
    if other_location == 'back':
        return destination, ['handoff_to_home_front']
    return destination, ['handoff_to_home_back', 'queue_advance']


class PathController:
    """Track registered body-heading paths; no spin or goal-seeking curve at the wall."""
    def __init__(self, segments, config):
        self.segments, self.config = segments, config
        self.index = self.progress = 0
        self.entry_positioned = False
        self.entry_heading_set = False

    def step(self, current):
        cfg = self.config; segment = self.segments[self.index]
        points = segment['poses']; end = dict(zip(('x','y','yaw'),points[-1]))
        x,y,yaw = relative(end,current); distance = math.hypot(x,y)
        state = dict(phase=segment['name'], linear=0., angular=0., distance_m=distance,
                     yaw_error=yaw, segment_index=self.index)
        tolerance = math.radians(cfg['yaw_tolerance_deg'])
        if segment['direction'] == 0:
            # Nav2 and the camera can disagree at handoff. Reach the open-space
            # reference with the camera before turning onto the registered curve.
            if not self.entry_positioned:
                self.entry_positioned = distance <= cfg['position_tolerance_m']
                if not self.entry_positioned:
                    heading = math.atan2(y,x)
                    self.entry_heading_set |= abs(heading) <= tolerance
                    speed = min(cfg['speed_mps'],distance*.6)
                    state.update(phase='waiting_entry_position',
                                 linear=speed*max(0.,math.cos(heading)) if self.entry_heading_set else 0.,
                                 angular=max(-cfg['angular_speed_rps'],
                                             min(cfg['angular_speed_rps'],1.5*heading)))
                    return state
            complete = abs(yaw) <= tolerance
            state['angular'] = max(-cfg['angular_speed_rps'],min(cfg['angular_speed_rps'],yaw))
        else:
            direction = segment['direction']
            nearest = min(range(self.progress,len(points)),
                          key=lambda i:math.hypot(points[i][0]-current['x'],points[i][1]-current['y']))
            self.progress = nearest
            following = self.segments[self.index+1] if self.index+1<len(self.segments) else None
            continuous = (following is not None and following.get('straight')
                          and following['direction']==direction
                          and math.dist(points[-1][:2],following['poses'][0][:2])<1e-4)
            if segment.get('advance_only'):
                along = relative(current,end)[0]
                complete = along >= -cfg['position_tolerance_m']
            elif continuous:
                # A curve endpoint is a transit point, not a parking goal.
                complete = distance <= cfg['position_tolerance_m'] or nearest == len(points)-1
                if complete:
                    self.index += 1; self.progress = 0
                    return self.step(current)
            else:
                complete = distance <= cfg['position_tolerance_m'] and abs(yaw) <= tolerance
            tracking_points = points + following['poses'][1:] if continuous else points
            look = nearest; length = 0.
            while look+1 < len(tracking_points) and length < cfg['lookahead_m']:
                length += math.dist(tracking_points[look][:2],tracking_points[look+1][:2]); look += 1
            target = dict(zip(('x','y','yaw'),tracking_points[look]))
            if segment.get('straight'):
                # Continue the tangent as a steering reference, not a shrinking-radius
                # turn around the endpoint. Angular speed always comes with translation.
                along = relative(current,end)[0]
                target = offset(end,along+direction*cfg['lookahead_m'])
            tx,ty,_ = relative(target,current)
            curvature = 2*ty/max(tx*tx+ty*ty,.0004)
            remaining = math.dist(tracking_points[-1][:2],[current['x'],current['y']])
            speed = min(cfg['speed_mps'],max(.008,remaining*.6))
            if abs(curvature)>1e-9:
                speed = min(speed,cfg['angular_speed_rps']/abs(curvature))
            state.update(linear=direction*speed, angular=direction*speed*curvature)
        if complete:
            state.update(linear=0.,angular=0.)
            if self.index+1 == len(self.segments):
                state['phase'] = 'advanced' if segment.get('advance_only') else 'aligned'
            else:
                self.index += 1; self.progress = 0
        return state
