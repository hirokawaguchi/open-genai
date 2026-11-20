import {
  decideWhisperPayload,
  EXTRACTED_TOO_LARGE,
  WHISPER_UPLOAD_LIMIT_BYTES,
  type WhisperExtraction,
  whisperFileKind,
} from './whisperUploadLimit';

export class WhisperUploadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WhisperUploadError';
  }
}

type AudioCodec = import('mediabunny').AudioCodec;
type OutputFormat = import('mediabunny').OutputFormat;

function replaceExtension(name: string, ext: string): string {
  const dot = name.lastIndexOf('.');
  const base = dot > 0 ? name.slice(0, dot) : name;
  return `${base}.${ext}`;
}

function outputFor(
  mb: typeof import('mediabunny'),
  codec: AudioCodec,
): { ext: string; mime: string; format: OutputFormat } | null {
  const candidates = [
    { ext: 'm4a', mime: 'audio/mp4', format: new mb.Mp4OutputFormat({ fastStart: false }) },
    { ext: 'webm', mime: 'audio/webm', format: new mb.WebMOutputFormat() },
    { ext: 'mp3', mime: 'audio/mpeg', format: new mb.Mp3OutputFormat() },
    { ext: 'flac', mime: 'audio/flac', format: new mb.FlacOutputFormat() },
    { ext: 'wav', mime: 'audio/wav', format: new mb.WavOutputFormat() },
  ];
  return candidates.find((item) => item.format.getSupportedAudioCodecs().includes(codec)) ?? null;
}

// 映像を捨て、音声パケットだけをコピーする。再エンコードはしない。
async function extractAudioTrack(file: File): Promise<File | 'no-video-track' | 'no-audio'> {
  const mb = await import('mediabunny');
  const input = new mb.Input({ formats: mb.ALL_FORMATS, source: new mb.BlobSource(file) });
  try {
    const video = await input.getPrimaryVideoTrack();
    if (!video) {
      return 'no-video-track';
    }
    const audio = await input.getPrimaryAudioTrack();
    if (!audio) {
      return 'no-audio';
    }
    const codec = audio.codec;
    const targetFormat = codec ? outputFor(mb, codec) : null;
    if (!codec || !targetFormat) {
      throw new Error('音声トラックを取り出せませんでした。');
    }
    const duration = await audio.computeDuration();
    const stats = await audio.computePacketStats(32).catch(() => null);
    if (
      stats &&
      stats.averageBitrate > 0 &&
      duration > 0 &&
      (stats.averageBitrate / 8) * duration > WHISPER_UPLOAD_LIMIT_BYTES &&
      file.size > WHISPER_UPLOAD_LIMIT_BYTES
    ) {
      throw new WhisperUploadError(EXTRACTED_TOO_LARGE);
    }
    const target = new mb.BufferTarget();
    const output = new mb.Output({ format: targetFormat.format, target });
    const source = new mb.EncodedAudioPacketSource(codec);
    output.addAudioTrack(source, { languageCode: audio.languageCode });
    await output.start();
    const sink = new mb.EncodedPacketSink(audio);
    const decoderConfig = await audio.getDecoderConfig();
    const first = await audio.getFirstTimestamp();
    const shift = Math.min(0, first);
    let index = 0;
    for await (const packet of sink.packets()) {
      const timestamp = Math.max(0, packet.timestamp - shift);
      await source.add(
        packet.clone({ timestamp }),
        index === 0 ? { decoderConfig: decoderConfig ?? undefined } : undefined,
      );
      index += 1;
    }
    if (index === 0) {
      await output.cancel();
      return 'no-audio';
    }
    source.close();
    await output.finalize();
    const buffer = target.buffer;
    if (!buffer || buffer.byteLength === 0) {
      throw new Error('音声トラックを取り出せませんでした。');
    }
    return new File([buffer], replaceExtension(file.name, targetFormat.ext), {
      type: targetFormat.mime,
    });
  } finally {
    input.dispose();
  }
}

export async function prepareWhisperUpload(file: File): Promise<File> {
  let extraction: WhisperExtraction;
  let extracted: File | null = null;
  if (whisperFileKind(file) !== 'video') {
    extraction = 'not-video';
  } else {
    try {
      const result = await extractAudioTrack(file);
      if (result === 'no-video-track' || result === 'no-audio') {
        extraction = result;
      } else {
        extracted = result;
        extraction = { bytes: result.size };
      }
    } catch (caught) {
      if (caught instanceof WhisperUploadError) {
        throw caught;
      }
      extraction = 'failed';
    }
  }
  const decision = decideWhisperPayload({ originalBytes: file.size, extraction });
  if ('error' in decision) {
    throw new WhisperUploadError(decision.error);
  }
  if (decision.send === 'extracted' && extracted) {
    return extracted;
  }
  return file;
}
