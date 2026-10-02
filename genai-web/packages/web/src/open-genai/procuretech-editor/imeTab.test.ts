import { describe, expect, it } from 'vitest';
import { bindEditorImeTabGuard, editorTabSpaces, isImeTab } from './imeTab';

const tab = (init: KeyboardEventInit & { keyCode?: number }) => {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
  if (init.keyCode != null) {
    Object.defineProperty(event, 'keyCode', { get: () => init.keyCode });
  }
  return event;
};

describe('procuretech-editor/imeTab', () => {
  it('変換中の Tab はインデント対象にしない', () => {
    const event = { key: 'Tab', code: 'Tab', keyCode: 9, isComposing: true };
    expect(isImeTab(event, { composing: false, swallowTab: false })).toBe(true);
    expect(isImeTab(event, { composing: true, swallowTab: false })).toBe(true);
  });

  it('keyCode 229 の Tab も変換中として扱う', () => {
    expect(
      isImeTab(
        { key: 'Tab', code: 'Tab', keyCode: 229, isComposing: false },
        { composing: false, swallowTab: false },
      ),
    ).toBe(true);
  });

  it('変換確定直後の Tab は飲み込む', () => {
    expect(
      isImeTab(
        { key: 'Tab', code: 'Tab', keyCode: 9, isComposing: false },
        { composing: false, swallowTab: true },
      ),
    ).toBe(true);
  });

  it('変換外の Tab は通常のインデントに残す', () => {
    expect(
      isImeTab(
        { key: 'Tab', code: 'Tab', keyCode: 9, isComposing: false },
        { composing: false, swallowTab: false },
      ),
    ).toBe(false);
  });

  it('変換中の Tab は textarea の keydown まで届かない', () => {
    const root = document.createElement('div');
    const textarea = document.createElement('textarea');
    textarea.value = '調達の流れ';
    root.append(textarea);
    document.body.append(root);
    const unbind = bindEditorImeTabGuard(root, true);
    let reached = false;
    textarea.addEventListener('keydown', () => {
      reached = true;
    });

    textarea.dispatchEvent(tab({ key: 'Tab', code: 'Tab', isComposing: true }));

    expect(reached).toBe(false);
    expect(textarea.value).toBe('調達の流れ');
    unbind();
    root.remove();
  });

  it('予測候補が入った Tab では空白を足さない', async () => {
    const root = document.createElement('div');
    const textarea = document.createElement('textarea');
    textarea.value = '調達';
    root.append(textarea);
    document.body.append(root);
    const unbind = bindEditorImeTabGuard(root, true);
    root.addEventListener(
      'keydown',
      () => {
        textarea.value = '調達仕様書';
        textarea.dispatchEvent(new InputEvent('input', { bubbles: true }));
      },
      true,
    );

    textarea.dispatchEvent(tab({ key: 'Tab', code: 'Tab' }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(textarea.value).toBe('調達仕様書');
    unbind();
    root.remove();
  });

  it('予測候補が無い Tab は従来どおり空白を挿入する', async () => {
    const root = document.createElement('div');
    const textarea = document.createElement('textarea');
    textarea.value = '本文';
    root.append(textarea);
    textarea.selectionStart = 2;
    textarea.selectionEnd = 2;
    document.body.append(root);
    const unbind = bindEditorImeTabGuard(root, true);

    textarea.dispatchEvent(tab({ key: 'Tab', code: 'Tab' }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(textarea.value).toBe(`本文${editorTabSpaces()}`);
    unbind();
    root.remove();
  });

  it('macOS 以外では通常の Tab をエディタへ渡す', () => {
    const root = document.createElement('div');
    const textarea = document.createElement('textarea');
    textarea.value = '本文';
    root.append(textarea);
    document.body.append(root);
    const unbind = bindEditorImeTabGuard(root, false);
    let reached = false;
    textarea.addEventListener('keydown', () => {
      reached = true;
    });

    textarea.dispatchEvent(tab({ key: 'Tab', code: 'Tab' }));

    expect(reached).toBe(true);
    expect(textarea.value).toBe('本文');
    unbind();
    root.remove();
  });
});
