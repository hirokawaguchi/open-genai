import { describe, expect, it } from 'vitest';
import { sortByDisplayOrder } from '../../../../src/features/exapps/utils/displayOrder';

describe('sortByDisplayOrder', () => {
  it('puts the smaller display order first', () => {
    const sorted = sortByDisplayOrder([
      { id: 'late', displayOrder: 4 },
      { id: 'first', displayOrder: 0 },
      { id: 'mid', displayOrder: 2 },
    ]);
    expect(sorted.map((item) => item.id)).toEqual(['first', 'mid', 'late']);
  });

  it('keeps apps without an order in their original sequence, after numbered ones', () => {
    const sorted = sortByDisplayOrder([
      { id: 'plain-a' },
      { id: 'numbered', displayOrder: 1 },
      { id: 'plain-b', displayOrder: null },
    ]);
    expect(sorted.map((item) => item.id)).toEqual(['numbered', 'plain-a', 'plain-b']);
  });
});
