const DB_NAME = 'ibisoffice-playground';
const STORE = 'files';
const KEY = 'picked';

/**
 * オフィスへ渡すファイルを IndexedDB に置く。
 * エディタ側が `?local=1` で開くと、iframe がこの値を読んで削除する。
 */
export const stageOfficeFile = (name: string, bytes: Uint8Array): Promise<void> =>
  new Promise((resolve, reject) => {
    const open = indexedDB.open(DB_NAME, 1);
    open.onupgradeneeded = () => {
      if (!open.result.objectStoreNames.contains(STORE)) {
        open.result.createObjectStore(STORE);
      }
    };
    open.onerror = () => reject(open.error ?? new Error('IndexedDB を開けません'));
    open.onsuccess = () => {
      const db = open.result;
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put({ name, bytes }, KEY);
      tx.oncomplete = () => {
        db.close();
        resolve();
      };
      tx.onerror = () => reject(tx.error ?? new Error('ファイルを置けません'));
    };
  });
