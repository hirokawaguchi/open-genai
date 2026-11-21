import { describe, expect, it } from 'vitest';
import { swapTeamApp } from '../../../../src/features/team-apps/utils/reorderTeamApps';

const apps = [{ exAppId: 'a' }, { exAppId: 'b' }, { exAppId: 'c' }];

describe('swapTeamApp', () => {
  it('moves an app up and down by one row', () => {
    expect(swapTeamApp(apps, 'b', 'up')?.map((app) => app.exAppId)).toEqual(['b', 'a', 'c']);
    expect(swapTeamApp(apps, 'b', 'down')?.map((app) => app.exAppId)).toEqual(['a', 'c', 'b']);
  });

  it('does not move the first app up or the last app down', () => {
    expect(swapTeamApp(apps, 'a', 'up')).toBeNull();
    expect(swapTeamApp(apps, 'c', 'down')).toBeNull();
  });
});
