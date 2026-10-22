export interface Product {
  sku: string; name: string; station: 'load-a' | 'load-b';
  detector_class: string; class_id: number; initial_stock: number;
  physical_support: 'unverified';
  stock: { on_hand: number; reserved: number } | null; available: number | null;
}
export interface Item { sku: string; slot: number; item_id: string }
export interface InventoryItem extends Item { delivered: boolean; load_command_id: string; handoff_command_id: string | null }
export interface Session {
  id: string; label: string; robot_id: string; basket_id: string; state: string; checkout_requested: boolean;
  current_task: string | null; inventory: InventoryItem[]; error: string | null;
  created_at: number; completed_at: number | null;
  active_trip: string | null; basket_side: 'left' | 'right' | null; receipt_confirmed_at: number | null;
}
export interface Order { id: string; session_id: string; request_id: string; items: Record<string, number>; created_at: number; status: string; cancellable: boolean }
export interface Task {
  id: string; session_id: string; robot_id: string; kind: string; zone_id: string;
  device_id: string; items: Item[]; state: string; stopped_at: number | null; arm_clear: boolean;
}
export interface Command {
  id: string; task_id: string; session_id: string; device_id: string; kind: string; status: string;
  sent_at: number | null; accepted_at: number | null;
  result: { kind: string; data: Record<string, unknown> } | null;
}
export interface Snapshot {
  motion_backend?: string; route_version?: number;
  run_id: string; mode: 'mock' | 'hardware'; test_only: boolean; test_hold: string | null; sessions: Record<string, Session>; orders: Record<string, Order>;
  tasks: Record<string, Task>; commands: Record<string, Command>;
  zones: Record<string, { owner?: string | null; queue?: string[]; busy?: boolean; mine?: boolean; waiting?: number }>;
  devices?: Record<string, { connected: boolean; forced_offline: boolean }>;
  basket?: { session_id: string; task_id: string; basket_id: string; at: number } | null;
  products: Product[]; capacity: number; server_time: number; heartbeat_at: number | null; permits?: number;
  cart_capacity: number;
  trips: Record<string, { id: string; session_id: string; number: number; state: string; unit_ids: string[] }>;
  units: Record<string, { id: string; session_id: string; sku: string; state: string; trip_id: string | null; slot: number | null }>;
  gateway_mode?: 'distributed';
  gateways?: Record<string, { label: string; devices: string[]; capabilities: string[]; role?: 'test' | 'control'; instance_id: string | null; heartbeat_at: number | null; connected: boolean }>;
}
export interface Audit {
  seq: number; at: number; kind: string; session_id: string | null; task_id: string | null;
  command_id: string | null; mode: string; detail: Record<string, unknown>;
}
