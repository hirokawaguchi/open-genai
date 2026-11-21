type Ordered = { displayOrder?: number | null };

/** 表示順の小さいものを前に出す。番号が無いものは、これまでの並びのまま後ろに残す。 */
export const sortByDisplayOrder = <T extends Ordered>(items: T[]): T[] =>
  items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const ao =
        typeof a.item.displayOrder === 'number' ? a.item.displayOrder : Number.MAX_SAFE_INTEGER;
      const bo =
        typeof b.item.displayOrder === 'number' ? b.item.displayOrder : Number.MAX_SAFE_INTEGER;
      if (ao !== bo) {
        return ao - bo;
      }
      return a.index - b.index;
    })
    .map(({ item }) => item);
