/** ピンのキー（teamId + itemId）を 1 つの文字列にまとめる */
export const toPinKey = (teamId: string, itemId: string): string => `${teamId}::${itemId}`;
