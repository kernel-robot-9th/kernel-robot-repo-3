"""One customer/order, with an independent three-slot execution per robot."""
from copy import deepcopy


class OrderFleet:
    def _runs(self, session):
        return list(session['robot_runs'].values()) if session.get('robot_runs') else [session]

    def _execution_session(self, sid, robot):
        session = self._session(sid)
        return session.get('robot_runs', {}).get(robot, session)

    def _assign_order_robots(self, session, order):
        if not self.readiness.get('parallel_order') or sum(order['items'].values()) <= self.cart_capacity:
            return
        from .domain import require
        other = next((r for r, v in self.state['robots'].items() if v['session_id'] is None), None)
        require(other and not session['inventory'] and not session['current_task'],
                '6개 동시 적재는 빈 로봇 두 대로 새 주문을 시작하세요')
        robots = [session['robot_id'], other]
        session['robot_runs'] = {}
        for robot in robots:
            run = {k: deepcopy(v) for k, v in session.items() if k not in ('token_hash', 'robot_runs')}
            run.update(robot_id=robot, basket_side='left' if robot == 'pinky-1' else 'right')
            session['robot_runs'][robot] = run
            self.state['robots'][robot]['session_id'] = session['id']
        units = sorted((u for u in self.state['units'].values() if u['order_id'] == order['id']),
                       key=lambda u: self.products[u['sku']]['station'])
        for index, unit in enumerate(units):
            unit['robot_id'] = robots[index // self.cart_capacity]
        self._log('order_robots_assigned', {'order_id': order['id'], 'robots': robots}, session_id=session['id'])

    def _handoff_allowed(self, run):
        if not self.readiness.get('handoff_arrival_only'):
            return True
        root = self._session(run['id'])
        return (run['robot_id'] == root['robot_id'] and
                all(u['state'] in ('LOADED', 'DELIVERED', 'CANCELLED')
                    for u in self.state['units'].values() if u['session_id'] == run['id']) and
                all(not r['current_task'] or self.state['tasks'][r['current_task']]['state'] == 'WAIT_LOADED'
                    for r in self._runs(root)))

    def _summarize_runs(self):
        for root in self.state['sessions'].values():
            if not root.get('robot_runs'):
                continue
            runs = self._runs(root)
            root['robot_ids'] = [r['robot_id'] for r in runs]
            root['inventory'] = [i for r in runs for i in r['inventory']]
            root['current_task'] = next((r['current_task'] for r in runs if r['current_task']), None)
            root['error'] = next((r['error'] for r in runs if r['error']), None)
            if root['error']:
                root['state'] = 'ERROR'
            elif any(r['state'] == 'WAIT_UNLOAD' for r in runs):
                root['state'] = 'WAIT_UNLOAD'
            elif all(r['state'] == 'COMPLETED' for r in runs):
                root['state'] = 'COMPLETED'
