import { describe, expect, it } from 'vitest';
import { partitionPinnedApps } from '@/open-genai/app-pins/partitionPinnedApps';
import type { AppPin } from '@/open-genai/app-pins/types';

const COMMON = '00000000-0000-0000-0000-000000000000';

const filteredTeams = [
  {
    teamIdKey: COMMON,
    teamData: { teamName: '共通アプリ' },
    filteredExApps: [
      { label: 'ナレッジ検索', value: 'rag', description: 'd', isDefault: false },
      { label: 'チャット', value: 'chat', description: 'd', isDefault: true },
    ],
  },
  {
    teamIdKey: 'team-1',
    teamData: { teamName: 'チーム1' },
    filteredExApps: [
      { label: 'アプリA', value: 'app-a', description: 'd', isDefault: false },
      { label: 'アプリB', value: 'app-b', description: 'd', isDefault: false },
    ],
  },
];

describe('partitionPinnedApps', () => {
  it('returns no pinned items and all teams when there are no pins', () => {
    const { pinnedItems, remainingTeams } = partitionPinnedApps(filteredTeams, []);
    expect(pinnedItems).toHaveLength(0);
    expect(remainingTeams).toHaveLength(2);
    expect(remainingTeams[0].filteredExApps).toHaveLength(2);
  });

  it('extracts pinned apps across categories and removes them from teams', () => {
    const pins: AppPin[] = [
      { teamId: 'team-1', itemId: 'app-b', displayOrder: 0 },
      { teamId: COMMON, itemId: 'chat', displayOrder: 1 },
    ];
    const { pinnedItems, remainingTeams } = partitionPinnedApps(filteredTeams, pins);

    expect(pinnedItems.map((p) => p.app.value)).toEqual(['app-b', 'chat']);
    expect(pinnedItems[0].teamName).toBe('チーム1');
    expect(pinnedItems[1].teamName).toBe('共通アプリ');

    const common = remainingTeams.find((t) => t.teamIdKey === COMMON);
    const team1 = remainingTeams.find((t) => t.teamIdKey === 'team-1');
    expect(common?.filteredExApps.map((a) => a.value)).toEqual(['rag']);
    expect(team1?.filteredExApps.map((a) => a.value)).toEqual(['app-a']);
  });

  it('orders pinned items by displayOrder', () => {
    const pins: AppPin[] = [
      { teamId: COMMON, itemId: 'chat', displayOrder: 5 },
      { teamId: 'team-1', itemId: 'app-a', displayOrder: 1 },
    ];
    const { pinnedItems } = partitionPinnedApps(filteredTeams, pins);
    expect(pinnedItems.map((p) => p.app.value)).toEqual(['app-a', 'chat']);
  });

  it('drops teams that become empty after removing pinned apps', () => {
    const pins: AppPin[] = [
      { teamId: 'team-1', itemId: 'app-a', displayOrder: 0 },
      { teamId: 'team-1', itemId: 'app-b', displayOrder: 1 },
    ];
    const { remainingTeams } = partitionPinnedApps(filteredTeams, pins);
    expect(remainingTeams.find((t) => t.teamIdKey === 'team-1')).toBeUndefined();
  });

  it('ignores pins that are not currently visible', () => {
    const pins: AppPin[] = [{ teamId: 'gone', itemId: 'ghost', displayOrder: 0 }];
    const { pinnedItems, remainingTeams } = partitionPinnedApps(filteredTeams, pins);
    expect(pinnedItems).toHaveLength(0);
    expect(remainingTeams).toHaveLength(2);
  });
});
