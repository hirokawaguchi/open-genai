import { useEffect, useMemo, useRef, useState } from 'react';
import { PiCastleTurretBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { SENGOKU_EXAPP_ID } from '@/layout/navItems';
import type { Command, GameState, HouseId, ProvinceId } from './types';
import { useSengokuActions, useSengokuConfig, useSengokuGame } from './useSengoku';

/** 家ごとの色（家 id をソートした順に割り当て、盤面を塗り分ける）。 */
const HOUSE_COLORS = [
  '#b91c1c', // 赤
  '#1d4ed8', // 青
  '#15803d', // 緑
  '#a16207', // 琥珀
  '#7c3aed', // 紫
  '#0e7490', // 藍
  '#db2777', // 桃
  '#4d7c0f', // 萌黄
  '#c2410c', // 橙
  '#334155', // 鈍色
];

const houseColorMap = (houseIds: HouseId[]): Record<HouseId, string> => {
  const sorted = [...houseIds].sort();
  const map: Record<HouseId, string> = {};
  sorted.forEach((id, i) => {
    map[id] = HOUSE_COLORS[i % HOUSE_COLORS.length];
  });
  return map;
};

type CmdType = 'develop' | 'recruit' | 'invade' | 'march' | 'diplomacy' | 'rest';

const RELATION_LABEL: Record<string, string> = {
  neutral: '中立',
  war: '交戦',
  ally: '同盟',
  self: '自家',
};

const SEASONS = ['春', '夏', '秋', '冬'];

export const SengokuPage = () => {
  const { documentTitle } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    SENGOKU_EXAPP_ID,
    '戦国国取り',
  );
  const { config, isLoading: configLoading, unavailable } = useSengokuConfig();
  const { game, mutate } = useSengokuGame();
  const { startGame, startObserver, abandonGame, playTurn, busy, error } = useSengokuActions();
  const [autoPlay, setAutoPlay] = useState(false);
  // 合戦記を発生順に少しずつ見せる（一括表示にしない）。null=未初期化。
  const [revealed, setRevealed] = useState<number | null>(null);
  const REVEAL_INTERVAL_MS = 450;
  const logLen = game?.log?.length ?? 0;

  const [cmdType, setCmdType] = useState<CmdType>('develop');
  const [develProvince, setDevelProvince] = useState<ProvinceId>('');
  const [recruitProvince, setRecruitProvince] = useState<ProvinceId>('');
  const [invadeFrom, setInvadeFrom] = useState<ProvinceId>('');
  const [invadeTo, setInvadeTo] = useState<ProvinceId>('');
  const [invadeTroops, setInvadeTroops] = useState<number>(10);
  const [marchFrom, setMarchFrom] = useState<ProvinceId>('');
  const [marchTo, setMarchTo] = useState<ProvinceId>('');
  const [marchTroops, setMarchTroops] = useState<number>(10);
  const [dipTarget, setDipTarget] = useState<HouseId>('');
  const [dipAction, setDipAction] = useState<'ally' | 'declare' | 'peace'>('ally');
  const [dipGift, setDipGift] = useState<number>(0);

  const colors = useMemo(
    () => houseColorMap(game ? Object.keys(game.houses) : Object.keys(config?.meta?.houses ?? {})),
    [game, config],
  );

  const player = game?.player_house ?? '';
  const ownProvinces = useMemo(
    () =>
      game
        ? Object.keys(game.provinces).filter((pid) => game.provinces[pid].owner === player)
        : [],
    [game, player],
  );

  const adjacentEnemies = useMemo(() => {
    if (!game || !invadeFrom) return [] as ProvinceId[];
    const neighbours = game.adjacency[invadeFrom] ?? [];
    return neighbours.filter((nb) => game.provinces[nb].owner !== player);
  }, [game, invadeFrom, player]);

  const adjacentOwn = useMemo(() => {
    if (!game || !marchFrom) return [] as ProvinceId[];
    const neighbours = game.adjacency[marchFrom] ?? [];
    return neighbours.filter((nb) => game.provinces[nb].owner === player);
  }, [game, marchFrom, player]);

  const onStart = async (house: HouseId) => {
    const g = await startGame(house);
    if (g) {
      await mutate({ game: g }, { revalidate: false });
    }
  };

  const onStartObserver = async () => {
    const g = await startObserver();
    if (g) {
      await mutate({ game: g }, { revalidate: false });
    }
  };

  const onAbandon = async () => {
    setAutoPlay(false);
    const ok = await abandonGame();
    if (ok) {
      await mutate({ game: null }, { revalidate: false });
    }
  };

  const buildCommand = (): Command | null => {
    switch (cmdType) {
      case 'develop':
        return develProvince ? { type: 'develop', province: develProvince } : null;
      case 'recruit':
        return recruitProvince ? { type: 'recruit', province: recruitProvince } : null;
      case 'invade':
        return invadeFrom && invadeTo && invadeTroops > 0
          ? { type: 'invade', from: invadeFrom, to: invadeTo, troops: invadeTroops }
          : null;
      case 'march':
        return marchFrom && marchTo && marchTroops > 0
          ? { type: 'march', from: marchFrom, to: marchTo, troops: marchTroops }
          : null;
      case 'diplomacy':
        return dipTarget
          ? {
              type: 'diplomacy',
              target: dipTarget,
              action: dipAction,
              gift: dipAction === 'declare' ? 0 : Math.max(0, Math.floor(dipGift || 0)),
            }
          : null;
      case 'rest':
        return { type: 'rest' };
      default:
        return null;
    }
  };

  const isObserver = !!game?.observer;

  const onPlay = async () => {
    if (isObserver) {
      const res = await playTurn(null);
      if (res) await mutate({ game: res.game }, { revalidate: false });
      return;
    }
    const command = buildCommand();
    if (!command) return;
    const res = await playTurn(command);
    if (res) {
      await mutate({ game: res.game }, { revalidate: false });
    }
  };

  // 合戦記の段階表示: 初回ロードは全件表示、以降は増えたぶんを 1 件ずつ出す。
  useEffect(() => {
    if (!game) {
      setRevealed(null);
      return;
    }
    setRevealed((prev) => (prev === null ? logLen : prev > logLen ? logLen : prev));
  }, [game, logLen]);

  // 1 本の永続タイマー（ディレクター）で、リビールと観戦の自動進行の両方を回す。
  // 複数エフェクトの結合で auto-play 中にタイマーが止まる問題を避けるため一元化する。
  const autoRunning = useRef(false);
  const dir = useRef({
    revealed,
    logLen,
    autoPlay,
    isObserver,
    status: game?.status,
    busy,
    playTurn,
    mutate,
    setRevealed,
    setAutoPlay,
  });
  dir.current = {
    revealed,
    logLen,
    autoPlay,
    isObserver,
    status: game?.status,
    busy,
    playTurn,
    mutate,
    setRevealed,
    setAutoPlay,
  };

  useEffect(() => {
    const id = window.setInterval(() => {
      const d = dir.current;
      // 1) まだ見せていないログがあれば 1 件公開する。
      if (d.revealed !== null && d.revealed < d.logLen) {
        d.setRevealed((r) => (r === null ? r : Math.min(d.logLen, r + 1)));
        return;
      }
      // 2) 追いついたら、観戦の自動進行なら次のターンへ。
      if (!d.autoPlay || !d.isObserver) return;
      if (d.status !== 'playing') {
        d.setAutoPlay(false);
        return;
      }
      if (autoRunning.current || d.busy) return;
      autoRunning.current = true;
      (async () => {
        try {
          const res = await d.playTurn(null);
          if (res) await d.mutate({ game: res.game }, { revalidate: false });
        } finally {
          autoRunning.current = false;
        }
      })();
    }, REVEAL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  // ゲーム中は縦スクロールせず 1 画面に収める（合戦記だけ枠内スクロール）。
  if (!unavailable && game) {
    return (
      <>
        <PageTitle title={documentTitle} />
        <SengokuBoard
          game={game}
          colors={colors}
          modelName={config?.llm?.model}
          upkeepPerTroop={config?.meta?.params?.upkeep_per_troop ?? 0.5}
          isObserver={isObserver}
          autoPlay={autoPlay}
          setAutoPlay={setAutoPlay}
          revealCount={revealed ?? logLen}
          busy={busy}
          error={error}
          cmdType={cmdType}
          setCmdType={setCmdType}
          ownProvinces={ownProvinces}
          adjacentEnemies={adjacentEnemies}
          adjacentOwn={adjacentOwn}
          develProvince={develProvince}
          setDevelProvince={setDevelProvince}
          recruitProvince={recruitProvince}
          setRecruitProvince={setRecruitProvince}
          invadeFrom={invadeFrom}
          setInvadeFrom={setInvadeFrom}
          invadeTo={invadeTo}
          setInvadeTo={setInvadeTo}
          invadeTroops={invadeTroops}
          setInvadeTroops={setInvadeTroops}
          marchFrom={marchFrom}
          setMarchFrom={setMarchFrom}
          marchTo={marchTo}
          setMarchTo={setMarchTo}
          marchTroops={marchTroops}
          setMarchTroops={setMarchTroops}
          dipTarget={dipTarget}
          setDipTarget={setDipTarget}
          dipAction={dipAction}
          setDipAction={setDipAction}
          dipGift={dipGift}
          setDipGift={setDipGift}
          onPlay={onPlay}
          onAbandon={onAbandon}
          buildCommand={buildCommand}
        />
      </>
    );
  }

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={SENGOKU_EXAPP_ID}
          fallbackTitle='戦国国取り'
          fallbackDescription='戦国時代を題材にしたターン制の国取りシミュレーション（お遊び）。'
          fallbackHowTo={
            <>
              <p>・大名家を選んで開始します。1 ターンに 1 つ命令を出せます。</p>
              <p>・開墾で石高、徴兵で兵を増やし、隣接する他家の国へ侵攻します。</p>
              <p>・敵対大名は AI が動かします。全土を統一すれば勝ちです。</p>
            </>
          }
        />

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              戦国国取りは現在有効化されていません
            </p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error || 'コンテナを profiles: ["sengoku"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile sengoku up -d{'\n'}
              # または .env に COMPOSE_PROFILES=sengoku
            </pre>
          </div>
        )}

        {!unavailable && !game && (
          <section className='flex flex-col gap-4'>
            <h2 className='flex items-center gap-2 text-std-18B-160'>
              <PiCastleTurretBold className='size-5' />
              大名家を選んで始める
            </h2>
            <p className='text-std-16N-170 text-solid-gray-700'>
              いずれかの家を選ぶと新しい対局が始まります。セーブは 1 局のみで、新規開始で上書きされます。
            </p>
            <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
              {Object.entries(config?.meta?.houses ?? {}).map(([hid, h]) => (
                <button
                  key={hid}
                  type='button'
                  onClick={() => onStart(hid)}
                  disabled={busy}
                  title={h.persona}
                  className='flex flex-col items-center gap-1.5 rounded-8 border border-solid-gray-420 bg-white px-4 py-4 text-center hover:bg-solid-gray-50 disabled:opacity-50'
                >
                  <span
                    className='inline-block size-6 rounded-full'
                    style={{ backgroundColor: colors[hid] }}
                  />
                  <span className='text-std-16B-150'>{h.name}家</span>
                  {h.trait && (
                    <span className='text-dns-14N-130 text-solid-gray-600'>{h.trait}</span>
                  )}
                  <span className='text-dns-14N-130 text-solid-gray-500'>
                    攻{h.attack?.toFixed(2)} 守{h.defense?.toFixed(2)}
                  </span>
                  <span className='text-dns-14N-130 text-solid-gray-500'>
                    内政{h.economy?.toFixed(2)} 好戦{h.aggression?.toFixed(2)}
                  </span>
                </button>
              ))}
            </div>
            <div className='flex flex-wrap items-center gap-3'>
              <Button
                type='button'
                variant='outline'
                size='md'
                onClick={onStartObserver}
                aria-disabled={busy}
              >
                観戦モードで見る（AIのみ・人間は指揮しない）
              </Button>
              {config?.llm?.model && (
                <span className='text-dns-14N-130 text-solid-gray-600'>
                  大名の軍師（AI モデル）: {config.llm.model}
                </span>
              )}
            </div>
            {error && (
              <p className='text-dns-16N-130 text-error-1' role='alert'>
                {error}
              </p>
            )}
          </section>
        )}
      </div>
    </LayoutBody>
  );
};

type BoardProps = {
  game: GameState;
  colors: Record<HouseId, string>;
  modelName?: string;
  upkeepPerTroop: number;
  isObserver: boolean;
  autoPlay: boolean;
  setAutoPlay: (v: boolean) => void;
  revealCount: number;
  busy: boolean;
  error: string | null;
  cmdType: CmdType;
  setCmdType: (v: CmdType) => void;
  ownProvinces: ProvinceId[];
  adjacentEnemies: ProvinceId[];
  adjacentOwn: ProvinceId[];
  develProvince: ProvinceId;
  setDevelProvince: (v: ProvinceId) => void;
  recruitProvince: ProvinceId;
  setRecruitProvince: (v: ProvinceId) => void;
  invadeFrom: ProvinceId;
  setInvadeFrom: (v: ProvinceId) => void;
  invadeTo: ProvinceId;
  setInvadeTo: (v: ProvinceId) => void;
  invadeTroops: number;
  setInvadeTroops: (v: number) => void;
  marchFrom: ProvinceId;
  setMarchFrom: (v: ProvinceId) => void;
  marchTo: ProvinceId;
  setMarchTo: (v: ProvinceId) => void;
  marchTroops: number;
  setMarchTroops: (v: number) => void;
  dipTarget: HouseId;
  setDipTarget: (v: HouseId) => void;
  dipAction: 'ally' | 'declare' | 'peace';
  setDipAction: (v: 'ally' | 'declare' | 'peace') => void;
  dipGift: number;
  setDipGift: (v: number) => void;
  onPlay: () => void;
  onAbandon: () => void;
  buildCommand: () => Command | null;
};

const SengokuBoard = (props: BoardProps) => {
  const { game, colors, busy, error, buildCommand } = props;
  const player = game.player_house;
  const season = game.season_index;
  const decided = game.status !== 'playing';

  // 隣接線（重複を避けて a<b のペアだけ）
  const edges: Array<[ProvinceId, ProvinceId]> = [];
  const seen = new Set<string>();
  for (const [a, neighbours] of Object.entries(game.adjacency)) {
    for (const b of neighbours) {
      const key = [a, b].sort().join('|');
      if (!seen.has(key)) {
        seen.add(key);
        edges.push([a, b]);
      }
    }
  }

  const globalSeason = (game.turn - 1) * 4 + game.season_index;
  const relationToPlayer = (hid: HouseId): string => {
    if (hid === player) return 'self';
    const key = [hid, player].sort().join('|');
    const rel = game.diplomacy[key] ?? 'neutral';
    if (rel === 'ally') {
      const until = game.alliance_expiry?.[key];
      if (typeof until === 'number') {
        const left = Math.max(0, until - globalSeason);
        return `同盟(あと${left}季)`;
      }
      return '同盟';
    }
    return RELATION_LABEL[rel] ?? '中立';
  };

  const isObserver = props.isObserver;

  // プレイヤーの収支（収入=石高合計、兵糧=総兵数×係数）。金を稼ぐ動機づけを見せる。
  const ownList = player ? Object.values(game.provinces).filter((p) => p.owner === player) : [];
  const playerIncome = ownList.reduce((s, p) => s + p.kokudaka, 0);
  const playerTroops = ownList.reduce((s, p) => s + (p.troops ?? 0), 0);
  const playerUpkeep = Math.round(playerTroops * props.upkeepPerTroop);

  // その家の総兵数。フォグで見えない国があるときは hasHidden=true。
  const troopsOf = (hid: HouseId): { known: number; hasHidden: boolean } => {
    let known = 0;
    let hasHidden = false;
    for (const p of Object.values(game.provinces)) {
      if (p.owner !== hid) continue;
      if (p.troops === null) hasHidden = true;
      else known += p.troops;
    }
    return { known, hasHidden };
  };

  // 合戦記は発生順に少しずつ出す（revealCount 件まで）。表示は新しい順（上が最新）。
  const shownLog = game.log.slice(0, props.revealCount);
  const chronicle = [...shownLog].reverse();
  const revealing = props.revealCount < game.log.length;

  return (
    <div className='flex h-[calc(100dvh-var(--header-height))] flex-col gap-2 p-3 lg:p-4'>
      {/* 上部バー */}
      <div className='flex flex-none flex-wrap items-center justify-between gap-2'>
        <div className='flex flex-wrap items-center gap-x-3 gap-y-1 text-std-14N-160'>
          <span className='text-std-16B-150'>戦国国取り</span>
          <span className='rounded-full bg-solid-gray-100 px-2 py-0.5'>
            第 {game.turn} 年 {SEASONS[season] ?? ''}
          </span>
          {isObserver || !player ? (
            <span className='rounded-full bg-solid-gray-100 px-2 py-0.5'>観戦モード</span>
          ) : (
            <>
              <span className='inline-flex items-center gap-1'>
                <span
                  className='inline-block size-3 rounded-full'
                  style={{ backgroundColor: colors[player] }}
                />
                {game.houses[player]?.name}家（金 {game.houses[player]?.gold}）
              </span>
              <span className='text-dns-14N-130 text-solid-gray-600'>
                収入 +{playerIncome} / 兵糧 −{playerUpkeep}（兵 {playerTroops}）
              </span>
            </>
          )}
          {props.modelName && (
            <span className='text-dns-14N-130 text-solid-gray-500'>
              軍師AI: {props.modelName}
            </span>
          )}
        </div>
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={props.onAbandon}
          aria-disabled={busy}
        >
          新規（この局を破棄）
        </Button>
      </div>

      {decided && (
        <div
          className={`flex-none rounded-8 border px-4 py-2 text-std-16B-150 ${
            game.status === 'lost'
              ? 'border-error-1 bg-red-50 text-error-1'
              : 'border-green-700 bg-green-50 text-green-900'
          }`}
          role='status'
        >
          {game.status === 'won' &&
            '天下統一を果たしました。勝利です。「新規」で再び乱世へ。'}
          {game.status === 'lost' &&
            '所領を失い、家は滅亡しました。敗北です。「新規」で再起を。'}
          {game.status === 'ended' &&
            `${game.winner ? `${game.houses[game.winner]?.name}家が天下を統一しました。` : '争覇は終わりました。'}「新規」でもう一局。`}
        </div>
      )}

      {/* メイン: 左=地図 / 右=命令・大名・合戦記 */}
      <div className='grid min-h-0 flex-1 gap-3 lg:grid-cols-[1.1fr_1fr]'>
        {/* 地図（枠いっぱいに広げ、家の凡例は枠内下部に重ねる） */}
        <section className='relative flex min-h-0 flex-col rounded-8 border border-solid-gray-300 bg-solid-gray-50'>
          <svg
            viewBox='0 0 100 100'
            preserveAspectRatio='xMidYMid meet'
            className='min-h-0 w-full flex-1'
            role='img'
            aria-label='勢力図'
          >
            {edges.map(([a, b]) => {
              const pa = game.provinces[a];
              const pb = game.provinces[b];
              return (
                <line
                  key={`${a}-${b}`}
                  x1={pa.x}
                  y1={pa.y}
                  x2={pb.x}
                  y2={pb.y}
                  stroke='#9ca3af'
                  strokeWidth={0.5}
                />
              );
            })}
            {/* まずマーカー（円＋兵数）をすべて描く */}
            {Object.entries(game.provinces).map(([pid, p]) => (
              <g key={`m-${pid}`}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={6}
                  fill={colors[p.owner]}
                  stroke={p.owner === player ? '#111827' : '#ffffff'}
                  strokeWidth={p.owner === player ? 1 : 0.5}
                />
                <text x={p.x} y={p.y + 1.2} textAnchor='middle' fontSize={3} fill='#ffffff'>
                  {p.troops === null ? '?' : p.troops}
                </text>
              </g>
            ))}
            {/* 国名ラベルは最前面に（他のマーカーの裏に隠れないよう2段目で描く）。
                白フチ（paint-order: stroke）で線や円に重なっても読めるようにする。 */}
            {Object.entries(game.provinces).map(([pid, p]) => (
              <text
                key={`l-${pid}`}
                x={p.x}
                y={p.y - 7.3}
                textAnchor='middle'
                fontSize={3.2}
                fill='#111827'
                stroke='#ffffff'
                strokeWidth={0.9}
                paintOrder='stroke'
                style={{ strokeLinejoin: 'round' }}
              >
                {p.name}
                {(isObserver || p.owner === player) && `（${p.kokudaka}）`}
              </text>
            ))}
          </svg>
          {/* 家の凡例（枠内下部にオーバーレイ） */}
          <div className='pointer-events-none absolute inset-x-2 bottom-1 flex flex-wrap gap-x-3 gap-y-0.5 rounded-4 bg-white/75 px-2 py-1 text-dns-14N-130'>
            {Object.entries(game.houses).map(([hid, h]) => (
              <span key={hid} className='inline-flex items-center gap-1'>
                <span
                  className='inline-block size-3 rounded-full'
                  style={{ backgroundColor: colors[hid], opacity: h.alive ? 1 : 0.3 }}
                />
                {h.name}家{!h.alive && '（滅亡）'}
              </span>
            ))}
          </div>
        </section>

        {/* 右カラム */}
        <div className='flex min-h-0 flex-col gap-2'>
          {/* 観戦モードの操作 */}
          {!decided && isObserver && (
            <section className='flex flex-none flex-wrap items-center gap-3 rounded-8 border border-solid-gray-300 p-3'>
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                onClick={props.onPlay}
                aria-disabled={busy || props.autoPlay}
              >
                {busy ? '進行中...' : '次の季節へ進める'}
              </Button>
              <label className='flex items-center gap-2 text-std-14N-160'>
                <input
                  type='checkbox'
                  checked={props.autoPlay}
                  onChange={(e) => props.setAutoPlay(e.target.checked)}
                />
                自動進行
              </label>
              {(busy || props.autoPlay) && (
                <span className='text-dns-14N-130 text-solid-gray-600'>
                  諸大名の軍議を進めています…
                </span>
              )}
            </section>
          )}

          {/* 命令パネル（プレイヤー操作時のみ） */}
          {!decided && !isObserver && (
            <section className='flex flex-none flex-col gap-2 rounded-8 border border-solid-gray-300 p-3'>
              <div className='flex flex-wrap gap-1.5'>
                {(
                  [
                    ['develop', '開墾'],
                    ['recruit', '徴兵'],
                    ['invade', '侵攻'],
                    ['march', '移動'],
                    ['diplomacy', '外交'],
                    ['rest', '休養'],
                  ] as [CmdType, string][]
                ).map(([v, label]) => (
                  <button
                    key={v}
                    type='button'
                    onClick={() => props.setCmdType(v)}
                    className={`rounded-full border px-3 py-1 text-std-14N-160 ${
                      props.cmdType === v
                        ? 'border-blue-900 bg-blue-900 text-white'
                        : 'border-solid-gray-420 bg-white text-solid-gray-800'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {props.cmdType === 'develop' && (
                <ProvinceSelect
                  label='開墾する自国の領地'
                  value={props.develProvince}
                  onChange={props.setDevelProvince}
                  options={props.ownProvinces}
                  game={game}
                />
              )}

              {props.cmdType === 'recruit' && (
                <ProvinceSelect
                  label='徴兵する自国の領地'
                  value={props.recruitProvince}
                  onChange={props.setRecruitProvince}
                  options={props.ownProvinces}
                  game={game}
                />
              )}

              {props.cmdType === 'invade' && (
                <div className='grid gap-2 md:grid-cols-3'>
                  <ProvinceSelect
                    label='出撃元（自国）'
                    value={props.invadeFrom}
                    onChange={(v) => {
                      props.setInvadeFrom(v);
                      props.setInvadeTo('');
                    }}
                    options={props.ownProvinces}
                    game={game}
                  />
                  <ProvinceSelect
                    label='侵攻先（隣接他家）'
                    value={props.invadeTo}
                    onChange={props.setInvadeTo}
                    options={props.adjacentEnemies}
                    game={game}
                  />
                  <div>
                    <Label size='sm'>出撃兵数</Label>
                    <input
                      type='number'
                      min={1}
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                      value={props.invadeTroops}
                      onChange={(e) => props.setInvadeTroops(Number(e.target.value))}
                    />
                    {props.invadeFrom && (
                      <p className='mt-0.5 text-dns-14N-130 text-solid-gray-600'>
                        守備兵: {game.provinces[props.invadeFrom]?.troops}
                      </p>
                    )}
                  </div>
                </div>
              )}

              {props.cmdType === 'march' && (
                <div className='grid gap-2 md:grid-cols-3'>
                  <ProvinceSelect
                    label='移動元（自国）'
                    value={props.marchFrom}
                    onChange={(v) => {
                      props.setMarchFrom(v);
                      props.setMarchTo('');
                    }}
                    options={props.ownProvinces}
                    game={game}
                  />
                  <ProvinceSelect
                    label='移動先（隣接する自国）'
                    value={props.marchTo}
                    onChange={props.setMarchTo}
                    options={props.adjacentOwn}
                    game={game}
                  />
                  <div>
                    <Label size='sm'>移動兵数</Label>
                    <input
                      type='number'
                      min={1}
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                      value={props.marchTroops}
                      onChange={(e) => props.setMarchTroops(Number(e.target.value))}
                    />
                    {props.marchFrom && (
                      <p className='mt-0.5 text-dns-14N-130 text-solid-gray-600'>
                        守備兵: {game.provinces[props.marchFrom]?.troops}
                      </p>
                    )}
                  </div>
                </div>
              )}

              {props.cmdType === 'diplomacy' && (
                <div className='grid gap-2 md:grid-cols-2'>
                  <div>
                    <Label size='sm'>相手の家</Label>
                    <select
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                      value={props.dipTarget}
                      onChange={(e) => props.setDipTarget(e.target.value)}
                    >
                      <option value=''>選択してください</option>
                      {Object.entries(game.houses)
                        .filter(([hid, h]) => hid !== player && h.alive)
                        .map(([hid, h]) => (
                          <option key={hid} value={hid}>
                            {h.name}家
                          </option>
                        ))}
                    </select>
                  </div>
                  <div>
                    <Label size='sm'>種類</Label>
                    <select
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                      value={props.dipAction}
                      onChange={(e) =>
                        props.setDipAction(e.target.value as 'ally' | 'declare' | 'peace')
                      }
                    >
                      <option value='ally'>同盟を結ぶ</option>
                      <option value='declare'>宣戦する</option>
                      <option value='peace'>和睦する</option>
                    </select>
                  </div>
                  {props.dipAction !== 'declare' && (
                    <div className='md:col-span-2'>
                      <Label size='sm'>貢金（任意・承諾されやすくなる。成立時のみ相手へ支払う）</Label>
                      <input
                        type='number'
                        min={0}
                        max={player ? game.houses[player]?.gold ?? 0 : 0}
                        className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                        value={props.dipGift}
                        onChange={(e) => props.setDipGift(Number(e.target.value))}
                      />
                      <p className='mt-0.5 text-dns-14N-130 text-solid-gray-600'>
                        {props.dipTarget
                          ? `${game.houses[props.dipTarget]?.name}家は${
                              props.dipAction === 'ally' ? '同盟' : '和睦'
                            }を断ることがあります（相手の気質・国力差・貢金で変わります）。`
                          : '同盟・和睦は相手の承諾が必要です。宣戦は無条件です。'}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {props.cmdType === 'rest' && (
                <p className='text-std-14N-160 text-solid-gray-700'>
                  この季節は兵を休めます（何もしません）。
                </p>
              )}

              {error && (
                <p className='text-dns-14N-130 text-error-1' role='alert'>
                  {error}
                </p>
              )}

              <div className='flex items-center gap-3'>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='md'
                  onClick={props.onPlay}
                  aria-disabled={busy || buildCommand() === null}
                >
                  {busy ? '進行中...' : 'この手で進める'}
                </Button>
                {busy && (
                  <span className='text-dns-14N-130 text-solid-gray-600'>
                    敵対大名が思案しています…
                  </span>
                )}
              </div>
            </section>
          )}

          {/* 大名家（コンパクト） */}
          <section className='flex-none'>
            <table className='w-full border-collapse text-std-14N-160'>
              <thead>
                <tr className='border-b border-solid-gray-300 text-left text-dns-14N-130 text-solid-gray-600'>
                  <th className='py-0.5 font-normal'>家</th>
                  <th className='py-0.5 font-normal'>領国</th>
                  <th className='py-0.5 font-normal'>兵</th>
                  <th className='py-0.5 font-normal'>金</th>
                  <th className='py-0.5 font-normal'>対あなた</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(game.houses).map(([hid, h]) => {
                  const count = Object.values(game.provinces).filter(
                    (p) => p.owner === hid,
                  ).length;
                  const t = troopsOf(hid);
                  const troopsText = t.hasHidden
                    ? t.known > 0
                      ? `${t.known}+?`
                      : '?'
                    : String(t.known);
                  return (
                    <tr key={hid} className='border-b border-solid-gray-200'>
                      <td className='py-0.5'>
                        <span className='inline-flex items-center gap-1'>
                          <span
                            className='inline-block size-3 rounded-full'
                            style={{ backgroundColor: colors[hid], opacity: h.alive ? 1 : 0.3 }}
                          />
                          {h.name}家{hid === player && '（自家）'}
                        </span>
                      </td>
                      <td className='py-0.5'>{count}</td>
                      <td className='py-0.5'>{troopsText}</td>
                      <td className='py-0.5'>{h.gold}</td>
                      <td className='py-0.5'>
                        {isObserver || hid === player ? '-' : relationToPlayer(hid)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          {/* 合戦記（枠内スクロール） */}
          <section className='flex min-h-0 flex-1 flex-col'>
            <h2 className='flex-none text-std-16B-150'>
              合戦記
              {revealing && (
                <span className='ml-2 text-dns-14N-130 font-normal text-solid-gray-500'>
                  進行中…
                </span>
              )}
            </h2>
            <div className='mt-1 min-h-0 flex-1 overflow-y-auto rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-3'>
              <ul className='flex flex-col gap-1.5 text-std-14N-160'>
                {chronicle.map((entry, i) => {
                  const mark = entry.event || !colors[entry.house];
                  return (
                    <li key={i} className='flex gap-1.5 leading-relaxed text-solid-gray-800'>
                      <span
                        aria-hidden
                        className='mt-1 flex-none'
                        style={{ color: mark ? '#6b7280' : colors[entry.house] }}
                        title={entry.house_name ? `${entry.house_name}家` : '天災・民'}
                      >
                        {mark ? '◆' : '●'}
                      </span>
                      <span>
                        <span className='mr-1 text-dns-14N-130 text-solid-gray-500'>
                          第{entry.turn}年{entry.season}
                        </span>
                        {entry.text}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

const ProvinceSelect = (props: {
  label: string;
  value: ProvinceId;
  onChange: (v: ProvinceId) => void;
  options: ProvinceId[];
  game: GameState;
}) => (
  <div>
    <Label size='sm'>{props.label}</Label>
    <select
      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
    >
      <option value=''>選択してください</option>
      {props.options.map((pid) => {
        const p = props.game.provinces[pid];
        return (
          <option key={pid} value={pid}>
            {p.name}（石高{p.kokudaka}・兵{p.troops}）
          </option>
        );
      })}
    </select>
  </div>
);
