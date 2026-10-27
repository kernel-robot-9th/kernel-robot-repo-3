"""Select Nav2 or visual-parking commands; no lease/time/speed rejection."""


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-id', default='pinky-1')
    parser.add_argument('--domain-id', type=int, default=1)
    parser.add_argument('--lease-topic', default=None, help='Accepted for existing launch commands; unused.')
    parser.add_argument('--output-topic', default='/cartrina/p1/drive_cmd_vel')
    args = parser.parse_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from geometry_msgs.msg import Twist
    from std_msgs.msg import String
    rclpy.init(args=[], domain_id=args.domain_id)
    node = Node(f"cartrina_p{args.robot_id.split('-')[-1]}_drive_gate")
    number = args.robot_id.split('-')[-1]
    output = node.create_publisher(Twist, args.output_topic, 10)
    selected = ['nav2']
    def forward(source, message):
        if selected[0] == source:
            output.publish(message)
    def select_source(message):
        selected[0] = message.data
        output.publish(Twist())
    qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                     reliability=ReliabilityPolicy.RELIABLE)
    subscriptions = [
        node.create_subscription(Twist, '/cmd_vel', lambda m: forward('nav2', m), 10),
        node.create_subscription(Twist, f'/cartrina/p{number}/parking_cmd_vel',
                                 lambda m: forward('parking', m), 10),
        node.create_subscription(String, f'/cartrina/p{number}/control_source', select_source, qos)]
    try:
        rclpy.spin(node)
    finally:
        output.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
