import type { ExApp, ListTeamExAppsResponse } from 'genai-web';

export const swapTeamApp = <T extends { exAppId: string }>(
  apps: T[],
  exAppId: string,
  direction: 'up' | 'down',
): T[] | null => {
  const index = apps.findIndex((app) => app.exAppId === exAppId);
  const target = direction === 'up' ? index - 1 : index + 1;
  if (index < 0 || target < 0 || target >= apps.length) {
    return null;
  }
  const next = apps.slice();
  const current = next[index];
  next[index] = next[target];
  next[target] = current;
  return next;
};

/** ページの件数を保ったまま、並べ替えたアプリを入れ直す。 */
export const placeTeamApps = (
  pages: ListTeamExAppsResponse[] | undefined,
  ordered: ExApp[],
): ListTeamExAppsResponse[] => {
  if (!pages || pages.length === 0) {
    return [{ teamExApps: ordered, lastEvaluatedKey: null }];
  }
  let cursor = 0;
  return pages.map((page) => {
    const size = page.teamExApps.length;
    const teamExApps = ordered.slice(cursor, cursor + size);
    cursor += size;
    return { ...page, teamExApps };
  });
};
