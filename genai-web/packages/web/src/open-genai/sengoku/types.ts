export type HouseId = string;
export type ProvinceId = string;

export type Relation = 'neutral' | 'war' | 'ally' | 'self';

export type Province = {
  name: string;
  owner: HouseId;
  kokudaka: number;
  /** フォグで隠されている国は null（隣接外は兵力が見えない） */
  troops: number | null;
  x: number;
  y: number;
  fog?: boolean;
};

export type House = {
  name: string;
  gold: number;
  alive: boolean;
  is_player: boolean;
  attack?: number;
  defense?: number;
  economy?: number;
  aggression?: number;
  loyalty?: number;
  trait?: string;
  persona?: string;
};

export type LogEntry = {
  turn: number;
  season: string;
  house: HouseId;
  house_name: string;
  text: string;
  /** 天災・民など勢力に属さない出来事 */
  event?: boolean;
};

export type GameState = {
  turn: number;
  season_index: number;
  player_house: HouseId | null;
  observer?: boolean;
  status: 'playing' | 'won' | 'lost' | 'ended';
  winner?: HouseId | null;
  provinces: Record<ProvinceId, Province>;
  adjacency: Record<ProvinceId, ProvinceId[]>;
  houses: Record<HouseId, House>;
  diplomacy: Record<string, Relation>;
  /** 同盟の有効期限（ペアキー -> 通算季節数）。 */
  alliance_expiry?: Record<string, number>;
  log: LogEntry[];
};

export type MetaHouse = {
  name: string;
  trait?: string;
  persona?: string;
  attack?: number;
  defense?: number;
  economy?: number;
  aggression?: number;
  loyalty?: number;
};

export type MetaProvince = { name: string; x: number; y: number };

export type SengokuMeta = {
  provinces: Record<ProvinceId, MetaProvince>;
  adjacency: Record<ProvinceId, ProvinceId[]>;
  houses: Record<HouseId, MetaHouse>;
  params: {
    develop_cost: number;
    develop_gain: number;
    kokudaka_max: number;
    recruit_cost: number;
    recruit_gain: number;
    min_garrison: number;
    troops_per_koku: number;
    upkeep_per_troop: number;
    alliance_term_seasons?: number;
    seasons: string[];
  };
};

export type SengokuConfig = {
  enabled?: boolean;
  error?: string;
  meta?: SengokuMeta;
  llm?: { model?: string; base_url?: string };
};

export type Command =
  | { type: 'develop'; province: ProvinceId }
  | { type: 'recruit'; province: ProvinceId }
  | { type: 'invade'; from: ProvinceId; to: ProvinceId; troops: number }
  | { type: 'march'; from: ProvinceId; to: ProvinceId; troops: number }
  | { type: 'diplomacy'; target: HouseId; action: 'ally' | 'declare' | 'peace'; gift?: number }
  | { type: 'rest' };

export type AiOrder = {
  house: HouseId;
  house_name: string;
  command: Command;
  comment?: string | null;
  source?: 'llm' | 'heuristic';
};

export type TurnResult = {
  game: GameState;
  ai_orders?: AiOrder[];
};
