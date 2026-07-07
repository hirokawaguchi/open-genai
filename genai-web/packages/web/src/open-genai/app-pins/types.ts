/** 利用者ごとの AI アプリ ピン留め上限 */
export const MAX_APP_PINS = 8;

/** サーバから返るピン留め 1 件 */
export type AppPin = {
  teamId: string;
  itemId: string;
  displayOrder: number;
};

export type AppPinsResponse = {
  pins: AppPin[];
};

/** ExAppList のカテゴリ内アプリ 1 件（useFilteredTeams の filteredExApps 要素） */
export type ExAppListItem = {
  label: string;
  value: string;
  description: string;
  isDefault?: boolean;
};

/** ピン留めセクション表示用（所属カテゴリ情報付き） */
export type PinnedAppItem = {
  teamIdKey: string;
  teamName: string;
  app: ExAppListItem;
};
