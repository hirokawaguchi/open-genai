/** 端末入力を UTF-8 バイト列にする。charCodeAt の下位 8bit 切り出しだと日本語が壊れる。 */
export const encodePty = (data: string): Uint8Array => new TextEncoder().encode(data);
