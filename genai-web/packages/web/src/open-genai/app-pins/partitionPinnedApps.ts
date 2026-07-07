import { toPinKey } from './appPinKey';
import type { AppPin, ExAppListItem, PinnedAppItem } from './types';

type FilteredTeam = {
  teamIdKey: string;
  teamData: { teamName: string };
  filteredExApps: ExAppListItem[];
};

export type PartitionedApps = {
  pinnedItems: PinnedAppItem[];
  remainingTeams: FilteredTeam[];
};

/**
 * カテゴリ横断でピン留めアプリを抽出し、各カテゴリからは除外する。
 * - `pinnedItems`: ピンの displayOrder 昇順（表示可能なもののみ）
 * - `remainingTeams`: ピン済みを除いたカテゴリ（空になったカテゴリは除外）
 */
export const partitionPinnedApps = (
  filteredTeams: FilteredTeam[],
  pins: AppPin[],
): PartitionedApps => {
  const pinnedKeys = new Set(pins.map((pin) => toPinKey(pin.teamId, pin.itemId)));

  // teamId + itemId で表示中アプリを引けるようにする
  const itemByKey = new Map<string, PinnedAppItem>();
  for (const team of filteredTeams) {
    for (const app of team.filteredExApps) {
      itemByKey.set(toPinKey(team.teamIdKey, app.value), {
        teamIdKey: team.teamIdKey,
        teamName: team.teamData.teamName,
        app,
      });
    }
  }

  const orderedPins = [...pins].sort((a, b) => a.displayOrder - b.displayOrder);
  const pinnedItems: PinnedAppItem[] = [];
  for (const pin of orderedPins) {
    const item = itemByKey.get(toPinKey(pin.teamId, pin.itemId));
    if (item) {
      pinnedItems.push(item);
    }
  }

  const remainingTeams = filteredTeams
    .map((team) => ({
      ...team,
      filteredExApps: team.filteredExApps.filter(
        (app) => !pinnedKeys.has(toPinKey(team.teamIdKey, app.value)),
      ),
    }))
    .filter((team) => team.filteredExApps.length > 0);

  return { pinnedItems, remainingTeams };
};
