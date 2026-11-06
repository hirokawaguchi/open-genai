import { useEffect, useMemo, useState } from 'react';
import { PiBookOpenBold } from 'react-icons/pi';
import { useSearchParams } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { BUDGET_EXAPP_ID } from '@/layout/navItems';
import type { BudgetData, BudgetRow, BudgetUnit, BudgetView } from './types';
import { useBudgetConfig, useBudgetData } from './useBudget';

const SHARE_CUTOFF = 0.02;
const DEFAULT_CODE = '442011';

const PURPOSE_COLOR: Record<string, string> = {
  議会費: '#8d99ae',
  総務費: '#6c757d',
  民生費: '#1f8a70',
  衛生費: '#4caf93',
  労働費: '#b08968',
  農林水産業費: '#7cb342',
  商工費: '#e09f3e',
  土木費: '#d4893a',
  消防費: '#e76f51',
  教育費: '#3d6f99',
  災害復旧費: '#9b2226',
  公債費: '#6d597a',
  諸支出金: '#a8a29a',
  前年度繰上充用金: '#c4b8a8',
};

const NATURE_COLOR: Record<string, string> = {
  人件費: '#3d6f99',
  物件費: '#7f95a8',
  維持補修費: '#90a4ae',
  扶助費: '#1f8a70',
  補助費等: '#d4893a',
  普通建設事業費: '#e09f3e',
  災害復旧事業費: '#9b2226',
  失業対策事業費: '#b08968',
  公債費: '#6d597a',
  積立金: '#6a994e',
  投資及び出資金: '#386641',
  貸付金: '#52b788',
  繰出金: '#bc6c25',
  前年度繰上充用金: '#c4b8a8',
};

type FlowItem = { name: string; value: number; aggregate?: boolean; gap?: boolean };
type Placed = FlowItem & { x: number; y: number; width: number; height: number; color: string; key: string };

const formatAmount = (thousandYen: number, pop: number, unit: BudgetUnit): string => {
  if (unit === 'per') {
    if (!pop) return '―';
    const yen = (thousandYen * 1000) / pop;
    const abs = Math.abs(yen);
    if (abs >= 10000) return `${(yen / 10000).toFixed(1)}万円/人`;
    return `${Math.round(yen).toLocaleString('ja-JP')}円/人`;
  }
  const yen = thousandYen * 1000;
  const sign = yen < 0 ? '-' : '';
  const abs = Math.abs(yen);
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}兆円`;
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(1)}億円`;
  if (abs >= 1e4) return `${sign}${Math.round(abs / 1e4).toLocaleString('ja-JP')}万円`;
  return `${sign}${Math.round(abs).toLocaleString('ja-JP')}円`;
};

const pairs = (names: string[], values: number[]): FlowItem[] =>
  names
    .map((name, index) => ({ name, value: values[index] || 0 }))
    .filter((item) => item.value > 0);

const foldItems = (items: FlowItem[], total: number, showAll: boolean): FlowItem[] => {
  const sorted = items.slice().sort((a, b) => b.value - a.value);
  if (showAll) return sorted;
  const shown: FlowItem[] = [];
  const rest: FlowItem[] = [];
  sorted.forEach((item) => {
    if (total > 0 && item.value / total >= SHARE_CUTOFF) shown.push(item);
    else rest.push(item);
  });
  if (rest.length) {
    shown.push({
      name: `${rest.length}科目`,
      value: rest.reduce((sum, item) => sum + item.value, 0),
      aggregate: true,
    });
  }
  return shown;
};

const revenueColor = (index: number): string => {
  const hue = 148 + (index % 8) * 6;
  return `hsl(${hue} 42% ${32 + (index % 3) * 6}%)`;
};

const ribbon = (x0: number, y0: number, h0: number, x1: number, y1: number, h1: number): string => {
  const dx = (x1 - x0) * 0.46;
  return `M ${x0} ${y0} C ${x0 + dx} ${y0}, ${x1 - dx} ${y1}, ${x1} ${y1} L ${x1} ${y1 + h1} C ${x1 - dx} ${y1 + h1}, ${x0 + dx} ${y0 + h0}, ${x0} ${y0 + h0} Z`;
};

const layoutColumn = (items: FlowItem[], scale: number, x: number): Placed[] => {
  let y = 0;
  return items.map((item) => {
    const height = item.value * scale;
    const node = { ...item, x, y, width: 18, height, color: '#c4b8a5', key: item.name };
    y += height + 7;
    return node;
  });
};

const columnHeight = (nodes: Placed[]): number => {
  if (!nodes.length) return 0;
  const last = nodes[nodes.length - 1];
  return last.y + last.height;
};

const SegButton = (props: { pressed: boolean; onClick: () => void; children: string }) => (
  <button
    type='button'
    aria-pressed={props.pressed}
    onClick={props.onClick}
    className={`rounded-full px-3 py-1.5 text-sm ${
      props.pressed ? 'bg-solid-gray-800 text-white' : 'text-solid-gray-700 hover:bg-solid-gray-100'
    }`}
  >
    {props.children}
  </button>
);

export const BudgetPage = () => {
  const { documentTitle, title, description, howToUse } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    BUDGET_EXAPP_ID,
    '自治体予算',
    '市区町村の普通会計決算を、歳入から歳出への流れで見ます。',
  );
  const { config, isLoading: configLoading, unavailable } = useBudgetConfig();
  const enabled = config?.enabled === true;
  const { data, isLoading: dataLoading } = useBudgetData(enabled);
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState('');
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    const root = document.getElementById('layoutRoot');
    const main = document.getElementById('mainContents');
    const column = main?.parentElement ?? null;
    const row = column?.parentElement ?? null;
    const html = document.documentElement;
    const prevHtmlOverflow = html.style.overflow;
    const prevRootHeight = root?.style.height ?? '';
    const prevRootOverflow = root?.style.overflow ?? '';
    html.style.overflow = 'hidden';
    if (root) {
      root.style.height = '100dvh';
      root.style.overflow = 'hidden';
    }
    const added: Array<[HTMLElement, string[]]> = [];
    const add = (el: HTMLElement | null, classes: string[]) => {
      if (!el) return;
      const next = classes.filter((name) => !el.classList.contains(name));
      if (next.length === 0) return;
      el.classList.add(...next);
      added.push([el, next]);
    };
    add(row, ['min-h-0', 'overflow-hidden']);
    add(column, ['min-h-0', 'overflow-hidden']);
    add(main, ['flex', 'min-h-0', 'flex-col', 'overflow-hidden']);
    const shell = document.getElementById('budget-shell');
    let node = shell?.parentElement ?? null;
    while (node && node !== main) {
      add(node, ['flex', 'min-h-0', 'h-full', 'flex-1', 'flex-col', 'overflow-hidden']);
      node = node.parentElement;
    }
    return () => {
      html.style.overflow = prevHtmlOverflow;
      if (root) {
        root.style.height = prevRootHeight;
        root.style.overflow = prevRootOverflow;
      }
      for (const [el, classes] of added) {
        el.classList.remove(...classes);
      }
    };
  }, []);

  const view: BudgetView = params.get('view') === 'nature' ? 'nature' : 'purpose';
  const unit: BudgetUnit = params.get('unit') === 'per' ? 'per' : 'total';
  const showAll = params.get('fold') === 'all';
  const prefFilter = params.get('pref') || '';

  const row = useMemo(() => {
    if (!data) return undefined;
    const code = params.get('code') || DEFAULT_CODE;
    return data.rows.find((item) => item.code === code) || data.rows.find((item) => item.code === DEFAULT_CODE) || data.rows[0];
  }, [data, params]);

  const prefs = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    const list: string[] = [];
    data.rows.forEach((item) => {
      if (!seen.has(item.pref)) {
        seen.add(item.pref);
        list.push(item.pref);
      }
    });
    return list;
  }, [data]);

  const hits = useMemo(() => {
    if (!data || !query.trim()) return [];
    const text = query.trim().toLowerCase();
    return data.rows
      .filter((item) => !prefFilter || item.pref === prefFilter)
      .filter((item) => item.name.toLowerCase().includes(text) || item.code.startsWith(text) || item.pref.includes(text))
      .slice(0, 12);
  }, [data, query, prefFilter]);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const selectRow = (code: string) => {
    setSelectedKey('');
    setSuggestOpen(false);
    setQuery('');
    setParam('code', code);
  };

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div
        id='budget-shell'
        className='mx-auto flex min-h-0 w-full max-w-(--page-width) flex-1 flex-col gap-2 overflow-hidden px-4 py-2 lg:px-6'
      >
        <div className='flex min-w-0 shrink-0 items-center gap-3'>
          <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{title}</h1>
          {description && (
            <p className='min-w-0 flex-1 truncate text-dns-14N-130 text-solid-gray-600' title={description}>
              {description}
            </p>
          )}
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='inline-flex shrink-0 items-center gap-1'
            onClick={() => setHelpOpen(true)}
          >
            <PiBookOpenBold aria-hidden={true} className='size-4' />
            使い方
          </Button>
        </div>

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170' role='status'>
            <p className='text-std-16B-150 text-solid-gray-900'>自治体予算は現在利用できません</p>
            <p className='mt-2 text-solid-gray-700'>{config?.error || 'profile budget で起動してください。'}</p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile budget up -d{'\n'}
              # または .env に COMPOSE_PROFILES=budget
            </pre>
          </div>
        )}

        {enabled && dataLoading && <p className='shrink-0 text-std-16N-170 text-solid-gray-700'>決算を読み込んでいます…</p>}

        {enabled && data && row && (
          <>
            <div className='flex shrink-0 flex-wrap items-end gap-3'>
              <label className='flex flex-col gap-1 text-xs text-solid-gray-600'>
                都道府県
                <select
                  className='h-10 rounded-full border border-solid-gray-420 bg-white px-3 text-sm text-solid-gray-900'
                  value={prefFilter}
                  onChange={(event) => setParam('pref', event.target.value)}
                >
                  <option value=''>全国</option>
                  {prefs.map((pref) => (
                    <option key={pref} value={pref}>{pref}</option>
                  ))}
                </select>
              </label>
              <label className='relative flex min-w-[220px] flex-1 flex-col gap-1 text-xs text-solid-gray-600'>
                自治体
                <input
                  className='h-10 rounded-full border border-solid-gray-420 bg-white px-3 text-sm text-solid-gray-900'
                  placeholder='自治体名または団体コード'
                  value={suggestOpen ? query : row.name}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setSuggestOpen(true);
                  }}
                  onFocus={() => setSuggestOpen(true)}
                />
                {suggestOpen && hits.length > 0 && (
                  <ul className='absolute top-16 z-10 max-h-72 w-full overflow-auto rounded-2xl border border-solid-gray-420 bg-white p-1 shadow-md'>
                    {hits.map((item) => (
                      <li key={item.code}>
                        <button
                          type='button'
                          className='flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm hover:bg-solid-gray-50'
                          onClick={() => selectRow(item.code)}
                        >
                          <span>{item.name}</span>
                          <span className='text-xs text-solid-gray-600'>{item.pref} {item.code}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </label>
              <div className='flex flex-col gap-1 text-xs text-solid-gray-600'>
                歳出の切り口
                <div className='flex rounded-full border border-solid-gray-420 bg-white p-1'>
                  <SegButton pressed={view === 'purpose'} onClick={() => { setSelectedKey(''); setParam('view', 'purpose'); }}>目的</SegButton>
                  <SegButton pressed={view === 'nature'} onClick={() => { setSelectedKey(''); setParam('view', 'nature'); }}>性質</SegButton>
                </div>
              </div>
              <div className='flex flex-col gap-1 text-xs text-solid-gray-600'>
                金額
                <div className='flex rounded-full border border-solid-gray-420 bg-white p-1'>
                  <SegButton pressed={unit === 'total'} onClick={() => setParam('unit', 'total')}>総額</SegButton>
                  <SegButton pressed={unit === 'per'} onClick={() => setParam('unit', 'per')}>1人あたり</SegButton>
                </div>
              </div>
              <div className='flex flex-col gap-1 text-xs text-solid-gray-600'>
                科目
                <div className='flex rounded-full border border-solid-gray-420 bg-white p-1'>
                  <SegButton pressed={!showAll} onClick={() => { setSelectedKey(''); setParam('fold', ''); }}>主要</SegButton>
                  <SegButton pressed={showAll} onClick={() => { setSelectedKey(''); setParam('fold', 'all'); }}>すべて</SegButton>
                </div>
              </div>
            </div>
            <div className='grid min-h-0 flex-1 items-stretch gap-3 lg:grid-cols-[minmax(0,1fr)_280px]'>
              <Sankey
                data={data}
                row={row}
                view={view}
                unit={unit}
                showAll={showAll}
                selectedKey={selectedKey}
                onSelect={setSelectedKey}
              />
              <Side
                data={data}
                row={row}
                view={view}
                unit={unit}
                selectedKey={selectedKey}
              />
            </div>
          </>
        )}
      </div>
      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            {howToUse ? (
              <ExAppUsageMarkdownRenderer content={howToUse} size='sm' />
            ) : (
              <div className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
                <p>・自治体名を選ぶと、令和6年度の決算が表示されます。</p>
                <p>・左は歳入、中央は普通会計、右は目的別または性質別の歳出です。</p>
                <p>・目的別と性質別は同じ歳出の別の分け方です。右の列を切り替えて見ます。</p>
                <p>・金額は総額と住民1人あたりを切り替えられます。</p>
              </div>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};

const Sankey = (props: {
  data: BudgetData;
  row: BudgetRow;
  view: BudgetView;
  unit: BudgetUnit;
  showAll: boolean;
  selectedKey: string;
  onSelect: (key: string) => void;
}) => {
  const { row, data, view, unit, showAll, selectedKey, onSelect } = props;
  const graph = useMemo(() => {
    const positive = Math.max(row.balance, 0);
    const negative = Math.max(-row.balance, 0);
    const midTotal = row.revTotal + negative;
    const revenue = foldItems(pairs(data.revenue, row.rev), row.revTotal, showAll);
    if (negative) revenue.push({ name: '歳入を超える歳出', value: negative, gap: true });
    const outNames = view === 'nature' ? data.nature : data.purpose;
    const outValues = view === 'nature' ? row.nature : row.purpose;
    const outgoing = foldItems(pairs(outNames, outValues), row.expTotal, showAll);
    if (positive) outgoing.push({ name: '歳入歳出差引', value: positive, gap: true });
    const scale = 820 / midTotal;
    const colorOf = (node: FlowItem, index: number, side: 'in' | 'out'): string => {
      if (node.gap) return side === 'in' ? '#9a8f80' : '#c4b8a5';
      if (node.aggregate) return '#c4b8a5';
      if (side === 'in') return revenueColor(index);
      const table = view === 'nature' ? NATURE_COLOR : PURPOSE_COLOR;
      return table[node.name] || '#8d99ae';
    };
    const left = layoutColumn(revenue, scale, 214).map((node, index) => ({
      ...node,
      color: colorOf(node, index, 'in'),
      key: `in:${node.name}`,
    }));
    const right = layoutColumn(outgoing, scale, 690).map((node, index) => ({
      ...node,
      color: colorOf(node, index, 'out'),
      key: `out:${node.name}`,
    }));
    const midHeight = midTotal * scale;
    const contentHeight = Math.max(columnHeight(left), columnHeight(right), midHeight);
    return { left, right, scale, midHeight, midY: (contentHeight - midHeight) / 2, contentHeight, midTotal };
  }, [data, row, view, showAll]);

  const dim = (key: string) => (selectedKey && selectedKey !== 'mid' && key !== selectedKey ? 0.18 : 1);
  const outTitle = view === 'nature' ? '性質別歳出' : '目的別歳出';
  const height = graph.contentHeight + 78;

  const leftLinks: { key: string; d: string; color: string }[] = [];
  let inflow = 0;
  graph.left.forEach((node) => {
    const thickness = node.value * graph.scale;
    leftLinks.push({
      key: node.key,
      color: node.color,
      d: ribbon(232, node.y + 46, node.height, 468, graph.midY + inflow + 46, thickness),
    });
    inflow += thickness;
  });
  const rightLinks: { key: string; d: string; color: string }[] = [];
  let outflow = 0;
  graph.right.forEach((node) => {
    const thickness = node.value * graph.scale;
    rightLinks.push({
      key: node.key,
      color: node.color,
      d: ribbon(490, graph.midY + outflow + 46, thickness, 690, node.y + 46, node.height),
    });
    outflow += thickness;
  });

  const label = (node: Placed, anchor: 'start' | 'end') => {
    if (node.height < 14) return null;
    const y = node.y + 46 + node.height / 2;
    const text = `${node.name} ${formatAmount(node.value, row.pop, unit)}`;
    return (
      <text x={anchor === 'end' ? 206 : 716} y={y} textAnchor={anchor} fontSize={12} dominantBaseline='middle'>
        {text}
      </text>
    );
  };

  return (
    <div className='h-full min-h-0 overflow-hidden rounded-2xl border border-solid-gray-420 bg-white'>
      <svg viewBox={`0 0 980 ${height}`} preserveAspectRatio='xMidYMid meet' className='block h-full w-full' role='img' aria-label={`${row.name}の${data.label}普通会計決算`}>
        <text x={20} y={22} fontSize={13} fontWeight={700}>歳入 {formatAmount(row.revTotal, row.pop, unit)}</text>
        <text x={479} y={22} fontSize={13} fontWeight={700} textAnchor='middle'>普通会計</text>
        <text x={716} y={22} fontSize={13} fontWeight={700}>{outTitle} {formatAmount(row.expTotal, row.pop, unit)}</text>
        <text x={20} y={40} fontSize={11} fill='#5e584f'>{data.label} 決算・千円を換算</text>
        {leftLinks.map((link) => (
          <path key={link.key} d={link.d} fill={link.color} opacity={0.45 * dim(link.key)} className='cursor-pointer' onClick={() => onSelect(selectedKey === link.key ? '' : link.key)} />
        ))}
        {rightLinks.map((link) => (
          <path key={link.key} d={link.d} fill={link.color} opacity={0.5 * dim(link.key)} className='cursor-pointer' onClick={() => onSelect(selectedKey === link.key ? '' : link.key)} />
        ))}
        {graph.left.map((node) => (
          <g key={node.key} opacity={dim(node.key)} className='cursor-pointer' onClick={() => onSelect(selectedKey === node.key ? '' : node.key)}>
            <rect x={node.x} y={node.y + 46} width={node.width} height={Math.max(node.height, 1)} rx={3} fill={node.color} />
            {label(node, 'end')}
          </g>
        ))}
        <g className='cursor-pointer' onClick={() => onSelect(selectedKey === 'mid' ? '' : 'mid')}>
          <rect x={468} y={graph.midY + 46} width={22} height={graph.midHeight} rx={3} fill='#234e3a' />
        </g>
        {graph.right.map((node) => (
          <g key={node.key} opacity={dim(node.key)} className='cursor-pointer' onClick={() => onSelect(selectedKey === node.key ? '' : node.key)}>
            <rect x={node.x} y={node.y + 46} width={node.width} height={Math.max(node.height, 1)} rx={3} fill={node.color} />
            {label(node, 'start')}
          </g>
        ))}
      </svg>
    </div>
  );
};

const Side = (props: {
  data: BudgetData;
  row: BudgetRow;
  view: BudgetView;
  unit: BudgetUnit;
  selectedKey: string;
}) => {
  const { data, row, view, unit, selectedKey } = props;
  const names = view === 'nature' ? data.nature : data.purpose;
  const values = view === 'nature' ? row.nature : row.purpose;
  const ranked = pairs(names, values).sort((a, b) => b.value - a.value).slice(0, 6);
  let picked = '帯をクリックすると内訳を固定できます。';
  if (selectedKey === 'mid') {
    picked = `普通会計 ${formatAmount(row.revTotal, row.pop, unit)}`;
  } else if (selectedKey.startsWith('in:') || selectedKey.startsWith('out:')) {
    const name = selectedKey.slice(selectedKey.indexOf(':') + 1);
    const pool = selectedKey.startsWith('in:') ? pairs(data.revenue, row.rev) : pairs(names, values);
    const found = pool.find((item) => item.name === name);
    const base = selectedKey.startsWith('in:') ? row.revTotal : row.expTotal;
    const share = found && base ? `全体の ${((found.value / base) * 100).toFixed(1)}%` : '';
    picked = found ? `${found.name}　${formatAmount(found.value, row.pop, unit)}　${share}` : name;
  }
  return (
    <aside className='h-full overflow-auto rounded-2xl border border-solid-gray-420 bg-white p-4'>
      <h2 className='text-xl font-semibold'>{row.name}</h2>
      <p className='mb-3 text-sm text-solid-gray-600'>{row.pref}　団体コード {row.code}　人口 {row.pop.toLocaleString('ja-JP')}人</p>
      <p className='mb-3 rounded-xl bg-solid-gray-50 px-3 py-2 text-sm'>{picked}</p>
      <dl className='mb-3 grid grid-cols-[7.5em_1fr] gap-y-1 text-sm'>
        <dt className='text-solid-gray-600'>歳入</dt><dd className='text-right'>{formatAmount(row.revTotal, row.pop, unit)}</dd>
        <dt className='text-solid-gray-600'>歳出</dt><dd className='text-right'>{formatAmount(row.expTotal, row.pop, unit)}</dd>
        <dt className='text-solid-gray-600'>差引</dt><dd className='text-right'>{formatAmount(row.balance, row.pop, unit)}</dd>
        <dt className='text-solid-gray-600'>財政力指数</dt><dd className='text-right'>{row.strength == null ? '―' : row.strength.toFixed(2)}</dd>
        <dt className='text-solid-gray-600'>経常収支比率</dt><dd className='text-right'>{row.currentRatio == null ? '―' : `${row.currentRatio.toFixed(1)}%`}</dd>
      </dl>
      <h3 className='mb-1 text-sm font-semibold'>{view === 'nature' ? '性質別の大きい順' : '目的別の大きい順'}</h3>
      <ol className='list-decimal pl-5 text-sm'>
        {ranked.map((item) => (
          <li key={item.name} className='my-1'>{item.name}　{formatAmount(item.value, row.pop, unit)}</li>
        ))}
      </ol>
      <p className='mt-3 text-xs text-solid-gray-600'>
        出典: <a className='underline' href={data.sourceUrl}>{data.source}</a>
        。金額の原単位は千円で、画面では円換算しています。{data.rows.length.toLocaleString('ja-JP')}団体。
      </p>
    </aside>
  );
};
