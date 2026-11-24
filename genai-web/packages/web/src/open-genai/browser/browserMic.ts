export type BrowserMicState = {
  stream: MediaStream | null;
  context: AudioContext | null;
  notice: string | null;
};

const EMPTY: BrowserMicState = { stream: null, context: null, notice: null };
let state: BrowserMicState = EMPTY;

export const getServerBrowserMic = (): BrowserMicState => EMPTY;
const listeners = new Set<() => void>();

const emit = () => {
  for (const listener of listeners) {
    listener();
  }
};

const live = (stream: MediaStream | null) =>
  Boolean(stream?.getAudioTracks().some((track) => track.readyState === 'live'));

export const getBrowserMic = (): BrowserMicState => state;

export const subscribeBrowserMic = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export const clearBrowserMicNotice = () => {
  if (!state.notice) {
    return;
  }
  state = { ...state, notice: null };
  emit();
};

/**
 * ブラウザを開くクリックの中で呼ぶ。
 * 許可の確認は、この操作に乗せる。セッションのあいだは入れたままにする。
 */
export const armBrowserMic = () => {
  const context =
    state.context && state.context.state !== 'closed' ? state.context : new AudioContext();
  void context.resume();
  state = { ...state, context };
  emit();
  if (live(state.stream)) {
    return;
  }
  void navigator.mediaDevices
    .getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      video: false,
    })
    .then((stream) => {
      const previous = state.stream;
      state = { ...state, stream, notice: null };
      emit();
      if (previous && previous !== stream) {
        for (const track of previous.getTracks()) {
          track.stop();
        }
      }
    })
    .catch(() => {
      state = {
        ...state,
        notice: 'マイクを使えませんでした。ブラウザのマイク許可を確認してください。',
      };
      emit();
    });
};

export const releaseBrowserMic = () => {
  const { stream, context } = state;
  state = EMPTY;
  emit();
  for (const track of stream?.getTracks() ?? []) {
    track.stop();
  }
  void context?.close();
};
