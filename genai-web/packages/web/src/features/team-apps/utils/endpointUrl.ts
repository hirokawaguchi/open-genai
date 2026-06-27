export const isValidHttpsEndpointUrl = (value: string): boolean => {
  if (value.trim() !== value) {
    return false;
  }

  try {
    const url = new URL(value);
    return (
      // Open GENAI(ローカル)では AI アプリ(マイクロサービス)へコンテナ間通信で
      // 到達するため http も許可する（例: http://dify-app:8004/invoke）。
      (url.protocol === 'https:' || url.protocol === 'http:') &&
      url.hostname.length > 0 &&
      url.username.length === 0 &&
      url.password.length === 0 &&
      url.hash.length === 0
    );
  } catch {
    return false;
  }
};
