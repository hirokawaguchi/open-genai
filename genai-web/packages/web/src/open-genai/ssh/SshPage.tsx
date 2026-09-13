import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { PiTerminalBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { SSH_EXAPP_ID } from '@/layout/navItems';
import { getIdToken } from '@/local/localAuth';
import { encodePty } from './encodePty';
import { sshWsUrl } from './sshWsUrl';
import type { SshHost, SshHostDraft } from './types';
import { emptyHostDraft } from './types';
import { useSshConfig, useSshHostActions, useSshHosts } from './useSsh';

const inputClass = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';
const TERM_COLS = 80;
const TERM_ROWS = 25;

/**
 * Web SSH 専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["ssh"] 未起動時は有効化手順を案内する。
 */
export const SshPage = () => {
  const { documentTitle } = useRegisteredAppMeta(COMMON_EXAPPS_TEAM_ID, SSH_EXAPP_ID, 'SSH 端末');
  const { config, isLoading: configLoading, unavailable } = useSshConfig();
  const serviceUp = !unavailable && config?.enabled !== false;
  const { hosts, isAdmin, isLoading, loadError, mutate } = useSshHosts(serviceUp);
  const { create, update, remove, submitting, error, setError } = useSshHostActions();

  const [hostId, setHostId] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectOpen, setConnectOpen] = useState(true);

  const termRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const selected = hosts.find((h) => h.id === hostId) ?? null;

  useEffect(() => {
    if (!hostId && hosts.length > 0) {
      setHostId(hosts[0].id);
    }
  }, [hostId, hosts]);

  useEffect(() => {
    if (selected && !connected) {
      setUsername(selected.default_username || '');
    }
  }, [selected, connected]);

  const disposeSession = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    terminalRef.current?.dispose();
    terminalRef.current = null;
    setConnected(false);
    setConnecting(false);
    setConnectOpen(true);
  }, []);

  useEffect(() => () => disposeSession(), [disposeSession]);

  const attachTerminal = useCallback(() => {
    if (!termRef.current) {
      return null;
    }
    terminalRef.current?.dispose();
    const term = new Terminal({
      cols: TERM_COLS,
      rows: TERM_ROWS,
      cursorBlink: true,
      // 比例の Noto Sans JP を先頭にするとセル幅が崩れ、英字が二重に見える。
      fontFamily:
        '"Noto Sans Mono", Menlo, Monaco, Consolas, "Osaka-Mono", "ＭＳ ゴシック", "Noto Sans JP", monospace',
      fontSize: 15,
      lineHeight: 1.15,
      letterSpacing: 0,
      rescaleOverlappingGlyphs: true,
      theme: { background: '#111827', foreground: '#f3f4f6' },
    });
    term.open(termRef.current);
    terminalRef.current = term;
    return term;
  }, []);

  const connect = async (e: FormEvent) => {
    e.preventDefault();
    setSessionError(null);
    if (!hostId) {
      setSessionError('接続先を選んでください。');
      return;
    }
    if (!username.trim() || !password) {
      setSessionError('ユーザー名とパスワードを入力してください。');
      return;
    }
    disposeSession();
    const term = attachTerminal();
    if (!term) {
      setSessionError('端末の初期化に失敗しました。');
      return;
    }
    const token = await getIdToken();
    if (!token) {
      setSessionError('認証が必要です。再ログインしてください。');
      return;
    }
    setConnecting(true);
    const api = import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT as string;
    const ws = new WebSocket(sshWsUrl(api));
    socketRef.current = ws;
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          token,
          hostId,
          username: username.trim(),
          password,
          cols: TERM_COLS,
          rows: TERM_ROWS,
        }),
      );
      setPassword('');
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') {
        term.write(new Uint8Array(ev.data as ArrayBuffer));
        return;
      }
      try {
        const msg = JSON.parse(ev.data) as {
          type?: string;
          message?: string;
          data?: string;
        };
        if (msg.type === 'ready') {
          setConnected(true);
          setConnecting(false);
          setConnectOpen(false);
          term.focus();
          return;
        }
        if (msg.type === 'error') {
          setSessionError(msg.message || '接続に失敗しました。');
          setConnecting(false);
          return;
        }
        if (msg.type === 'exit') {
          setConnected(false);
          setConnecting(false);
          term.writeln('\r\n[切断されました]');
          return;
        }
        if (msg.type === 'data' && typeof msg.data === 'string') {
          term.write(msg.data);
        }
      } catch {
        term.write(ev.data);
      }
    };
    ws.onerror = () => {
      setSessionError((prev) => prev || 'WebSocket の接続に失敗しました。');
      setConnecting(false);
    };
    ws.onclose = () => {
      setConnected(false);
      setConnecting(false);
      setConnectOpen(true);
    };
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(encodePty(data));
      }
    });
  };

  const disconnect = () => {
    disposeSession();
  };

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={SSH_EXAPP_ID}
          fallbackTitle='SSH 端末'
          fallbackDescription='管理者が登録した接続先へ、ブラウザから SSH でログインします。メンテナンスや SSH 上のサービス操作に使います。'
          fallbackHowTo={
            <>
              <p>・一覧から接続先を選び、ユーザー名とパスワードを入力して接続します。画面は 80×25 文字です。</p>
              <p>・接続先の追加・変更はシステム管理者だけが行えます。</p>
              <p>・パスワードはサーバに保存しません。接続が切れたら再入力してください。</p>
              {config?.idle_seconds != null && (
                <p>
                  ・操作がない状態が {Math.round(config.idle_seconds / 60)} 分続くと切断します。
                </p>
              )}
            </>
          }
        />

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>
              SSH 端末は現在有効化されていません
            </p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error || 'コンテナを profiles: ["ssh"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile ssh up -d{'\n'}# または .env に COMPOSE_PROFILES=ssh
            </pre>
          </div>
        )}

        {serviceUp && (
          <>
            <Disclosure
              className='rounded-8 border border-solid-gray-300 bg-white px-4 py-3'
              open={connectOpen}
              onToggle={(e) => {
                setConnectOpen(e.currentTarget.open);
              }}
            >
              <DisclosureSummary className='w-full'>
                <span className='flex items-center gap-2 text-std-16B-150'>
                  <PiTerminalBold aria-hidden />
                  接続
                  {connected && (
                    <span className='text-dns-14N-130 text-solid-gray-600'>（接続中）</span>
                  )}
                </span>
              </DisclosureSummary>
              <div className='mt-3'>
              {loadError && (
                <p className='mb-3 text-dns-16N-130 text-error-1' role='alert'>
                  {loadError}
                </p>
              )}
              <form onSubmit={connect} className='grid gap-4 md:grid-cols-2'>
                <div className='md:col-span-2'>
                  <Label htmlFor='ssh-host' size='sm'>
                    接続先
                  </Label>
                  <select
                    id='ssh-host'
                    className={inputClass}
                    value={hostId}
                    onChange={(e) => setHostId(e.target.value)}
                    disabled={connected || connecting || isLoading}
                  >
                    {hosts.length === 0 && <option value=''>登録された接続先がありません</option>}
                    {hosts.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.name}（{h.host}:{h.port}）
                      </option>
                    ))}
                  </select>
                  {selected?.description && (
                    <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                      {selected.description}
                    </p>
                  )}
                </div>
                <div>
                  <Label htmlFor='ssh-user' size='sm'>
                    ユーザー名
                  </Label>
                  <input
                    id='ssh-user'
                    className={inputClass}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete='username'
                    disabled={connected || connecting}
                    required
                  />
                </div>
                <div>
                  <Label htmlFor='ssh-password' size='sm'>
                    パスワード
                  </Label>
                  <input
                    id='ssh-password'
                    type='password'
                    className={inputClass}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete='current-password'
                    disabled={connected || connecting}
                    required={!connected}
                  />
                </div>
                <div className='flex flex-wrap items-center gap-3 md:col-span-2'>
                  <Button
                    type='submit'
                    variant='solid-fill'
                    size='md'
                    disabled={connected || connecting || hosts.length === 0}
                  >
                    {connecting ? '接続中...' : '接続'}
                  </Button>
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    onClick={disconnect}
                    disabled={!connected && !connecting}
                  >
                    切断
                  </Button>
                  {sessionError && (
                    <p className='text-dns-16N-130 text-error-1' role='alert'>
                      {sessionError}
                    </p>
                  )}
                </div>
              </form>
              </div>
            </Disclosure>

            <section className='w-fit overflow-hidden rounded-8 border border-solid-gray-800 bg-solid-gray-900'>
              <div ref={termRef} className='p-2 [&_.xterm]:[font-variant-ligatures:none]' />
            </section>

            {isAdmin && (
              <HostAdmin
                hosts={hosts}
                submitting={submitting}
                error={error}
                setError={setError}
                create={create}
                update={update}
                remove={remove}
                onChanged={mutate}
              />
            )}
          </>
        )}
      </div>
    </LayoutBody>
  );
};

type HostAdminProps = {
  hosts: SshHost[];
  submitting: boolean;
  error: string | null;
  setError: (value: string | null) => void;
  create: (input: SshHostDraft) => Promise<SshHost | null>;
  update: (hostId: string, input: SshHostDraft) => Promise<SshHost | null>;
  remove: (hostId: string) => Promise<boolean>;
  onChanged: () => Promise<unknown>;
};

const HostAdmin = ({
  hosts,
  submitting,
  error,
  setError,
  create,
  update,
  remove,
  onChanged,
}: HostAdminProps) => {
  const [draft, setDraft] = useState<SshHostDraft>(emptyHostDraft());
  const [editingId, setEditingId] = useState<string | null>(null);

  const startEdit = (host: SshHost) => {
    setEditingId(host.id);
    setDraft({
      name: host.name,
      host: host.host,
      port: host.port,
      default_username: host.default_username,
      description: host.description,
      host_key: host.host_key || '',
      enabled: host.enabled,
    });
    setError(null);
  };

  const resetDraft = () => {
    setEditingId(null);
    setDraft(emptyHostDraft());
    setError(null);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const saved = editingId ? await update(editingId, draft) : await create(draft);
    if (saved) {
      resetDraft();
      await onChanged();
    }
  };

  const onDelete = async (hostId: string) => {
    if (!window.confirm('この接続先を削除しますか？')) {
      return;
    }
    if (await remove(hostId)) {
      if (editingId === hostId) {
        resetDraft();
      }
      await onChanged();
    }
  };

  return (
    <Disclosure className='rounded-8 border border-solid-gray-300 bg-white px-4 py-3'>
      <DisclosureSummary className='w-full'>
        <span className='text-std-16B-150'>接続先の管理（システム管理者）</span>
      </DisclosureSummary>
      <div className='mt-3'>
      <p className='mt-0 text-dns-14N-130 text-solid-gray-700'>
        利用者が選べる SSH
        先です。ここ以外のホストへは接続できません。ホスト鍵を空にすると、次回接続時に取得して保存します。同じマシンの別コンテナへは、公開ポートなら
        host.docker.internal、同じ Docker
        ネットワークなら相手のサービス名を指定してください。localhost はコンテナ自身を指します。
      </p>
      <ul className='mt-4 flex flex-col gap-2'>
        {hosts.map((host) => (
          <li
            key={host.id}
            className='flex flex-wrap items-center justify-between gap-2 rounded-4 border border-solid-gray-300 px-3 py-2'
          >
            <div>
              <p className='text-std-16B-150'>
                {host.name}
                {!host.enabled && (
                  <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>無効</span>
                )}
              </p>
              <p className='text-dns-14N-130 text-solid-gray-700'>
                {host.host}:{host.port}
                {host.default_username ? ` / ${host.default_username}` : ''}
                {host.has_host_key ? ' / ホスト鍵あり' : ' / ホスト鍵未登録'}
              </p>
            </div>
            <div className='flex gap-2'>
              <Button type='button' variant='outline' size='sm' onClick={() => startEdit(host)}>
                編集
              </Button>
              <Button type='button' variant='text' size='sm' onClick={() => void onDelete(host.id)}>
                削除
              </Button>
            </div>
          </li>
        ))}
      </ul>

      <form onSubmit={onSubmit} className='mt-6 grid gap-3 md:grid-cols-2'>
        <div>
          <Label htmlFor='ssh-admin-name' size='sm'>
            表示名
          </Label>
          <input
            id='ssh-admin-name'
            className={inputClass}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
        </div>
        <div>
          <Label htmlFor='ssh-admin-host' size='sm'>
            ホスト
          </Label>
          <input
            id='ssh-admin-host'
            className={inputClass}
            value={draft.host}
            onChange={(e) => setDraft({ ...draft, host: e.target.value })}
            placeholder='host.docker.internal'
            required
          />
          <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
            ssh-app から見たホスト名です。この PC 上の別コンテナで公開しているポートなら
            host.docker.internal を使います。
          </p>
        </div>
        <div>
          <Label htmlFor='ssh-admin-port' size='sm'>
            ポート
          </Label>
          <input
            id='ssh-admin-port'
            type='number'
            min={1}
            max={65535}
            className={inputClass}
            value={draft.port}
            onChange={(e) => setDraft({ ...draft, port: Number(e.target.value) })}
            required
          />
        </div>
        <div>
          <Label htmlFor='ssh-admin-user' size='sm'>
            既定ユーザー名（任意）
          </Label>
          <input
            id='ssh-admin-user'
            className={inputClass}
            value={draft.default_username}
            onChange={(e) => setDraft({ ...draft, default_username: e.target.value })}
          />
        </div>
        <div className='md:col-span-2'>
          <Label htmlFor='ssh-admin-desc' size='sm'>
            説明（任意）
          </Label>
          <input
            id='ssh-admin-desc'
            className={inputClass}
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
        </div>
        <div className='md:col-span-2'>
          <Label htmlFor='ssh-admin-key' size='sm'>
            ホスト鍵（任意・OpenSSH 公開鍵形式）
          </Label>
          <textarea
            id='ssh-admin-key'
            className={inputClass}
            rows={3}
            value={draft.host_key}
            onChange={(e) => setDraft({ ...draft, host_key: e.target.value })}
            placeholder='ssh-ed25519 AAAA...'
          />
        </div>
        <label className='flex items-center gap-2 text-std-16N-170'>
          <input
            type='checkbox'
            checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          有効
        </label>
        <div className='flex flex-wrap items-center gap-3 md:col-span-2'>
          <Button type='submit' variant='solid-fill' size='md' disabled={submitting}>
            {editingId ? '更新' : '追加'}
          </Button>
          {editingId && (
            <Button type='button' variant='outline' size='md' onClick={resetDraft}>
              新規に戻す
            </Button>
          )}
          {error && (
            <p className='text-dns-16N-130 text-error-1' role='alert'>
              {error}
            </p>
          )}
        </div>
      </form>
      </div>
    </Disclosure>
  );
};
