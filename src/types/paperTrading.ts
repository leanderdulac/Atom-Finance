export interface PaperPlan {
  ticker:string; strategy:string; direction:string; close_by:string; expiry:string;
  legs:{symbol:string;side:string;quantity:number;limit_reference:number}[];
  modeled_max_loss_brl:number;
  entry:{underlying_trigger:number;quote_valid_until:string};
}
export interface PaperSummary {
  id:string;status:'watching'|'open'|'closed'|'cancelled';created_at:string;plan:PaperPlan;
  context:{source:string;provenance:'synthetic'|'user_supplied';fee_per_contract_side:number};
}
export interface PaperRecord extends PaperSummary {
  events:{id:string;created_at:string;kind:string;payload:{source:string;as_of:string;note:string};
    result:{net_pnl_brl?:number;entry_debit_brl?:number;fees_brl?:number;alerts:string[]}}[];
  eligible_for_live_trading:false;
}

export interface SourceSnapshotSummary {
  snapshot_id:string;provider:string;fetched_at:string;data_mode:string;
}
export interface SourceCheck {
  snapshot_id:string;trade_id:string;provider:string;checked_at:string;fetched_at:string;
  data_mode:string;operation_status:string;blockers:string[];note:string;
  eligible_for_observation:false;eligible_for_live_trading:false;
  legs:{symbol:string;observed_at:string|null;age_seconds:number|null;issues:string[];structural_checks_passed:boolean}[];
}

export interface OperatorTrade {
  id:string;status:'watching'|'open'|'closed'|'cancelled';created_at:string;
  ticker:string;strategy:string;direction:'long_bias'|'short_bias';
  quantity_per_leg:number;legs:string[];expiry:string;close_by:string;
  entry:{trigger:number;comparison:string;quote_valid_until:string;filled:boolean;debit_brl:number|null};
  exit:{invalidation:number;target:number;stop_loss_net_brl:number;take_profit_net_brl:number};
  modeled_max_loss_brl:number;risk_budget_brl:number;reserved_risk_brl:number|null;
  provenance:'synthetic'|'user_supplied';
  last:{kind:string;as_of:string|null;underlying:number|null;net_pnl_brl?:number;pnl_kind?:string;alerts:string[]} | null;
  eligible_for_live_trading:false;
}
export interface OperationsState {
  trades:OperatorTrade[];
  aggregate:{open_count:number;watching_count:number;reserved_risk_brl:number};
  eligible_for_live_trading:false;
}
