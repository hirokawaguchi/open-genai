import {
  OFFICIAL_APP_RUNTIME_LABEL,
  officialAppRuntimeKind,
} from './runtime';

export const OfficialAppRuntimeStatus = ({
  id,
  running,
}: {
  id: string;
  running: readonly string[] | undefined;
}) => {
  const kind = officialAppRuntimeKind(id, running);
  if (kind === 'unknown') {
    return null;
  }
  return (
    <span
      className={`text-dns-14N-130 ${
        kind === 'running' ? 'text-solid-gray-800' : 'text-solid-gray-600'
      }`}
    >
      {OFFICIAL_APP_RUNTIME_LABEL[kind]}
    </span>
  );
};
