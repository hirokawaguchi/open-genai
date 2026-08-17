(() => {
  const SCORE_KEY = "doccheck_guest_score_v1";
  const CHECKER_KEY = "doccheck_guest_checker_v1";
  const root = document.getElementById("root");
  const scoreEl = document.getElementById("score");

  const getCheckerKey = () => {
    let key = localStorage.getItem(CHECKER_KEY);
    if (!key) {
      key =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `g-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      localStorage.setItem(CHECKER_KEY, key);
    }
    return key;
  };

  const getScore = () => {
    try {
      return JSON.parse(localStorage.getItem(SCORE_KEY) || '{"count":0}');
    } catch {
      return { count: 0 };
    }
  };

  const bumpScore = () => {
    const s = getScore();
    s.count = (s.count || 0) + 1;
    localStorage.setItem(SCORE_KEY, JSON.stringify(s));
    renderScore();
  };

  const renderScore = () => {
    if (!scoreEl) return;
    const s = getScore();
    scoreEl.hidden = false;
    scoreEl.textContent = `この端末の累計チェック件数: ${s.count || 0}`;
  };

  const tokenFromPath = () => {
    const m = location.pathname.match(/\/public\/c\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  };

  const claimNext = async () => {
    const r = await fetch("/public/api/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ checker_key: getCheckerKey() }),
    });
    const j = await r.json().catch(() => ({}));
    if (j.token) {
      location.href = `/public/c/${j.token}`;
      return;
    }
    alert(j.error || "ただいまチェック可能な項目がありません");
  };

  const renderError = (msg) => {
    root.innerHTML = `<div class="card"><p class="error">${msg}</p>
      <p><a class="btn secondary" href="/public/">トップへ</a></p></div>`;
  };

  const renderDone = (msg) => {
    root.innerHTML = `<div class="card"><p class="ok">${msg}</p>
      <div class="actions">
        <a class="btn" id="next" href="#">次のチェック</a>
        <a class="btn secondary" href="/public/">トップへ</a>
      </div></div>`;
    document.getElementById("next").addEventListener("click", async (e) => {
      e.preventDefault();
      await claimNext();
    });
  };

  const MULTI_SEP = " | ";
  const parseMulti = (v) =>
    String(v || "")
      .split("|")
      .map((s) => s.trim())
      .filter(Boolean);

  const renderTask = (task) => {
    if (task.status === "done") {
      renderDone(task.message || "回答済みです。ご協力ありがとうございます。");
      return;
    }
    const fieldType = task.field_type || "text_single";
    const isChoice = fieldType === "choice" || fieldType === "choice_multi";
    const isMulti = fieldType === "choice_multi";
    const options = Array.isArray(task.choice_options) ? task.choice_options : [];
    const suggestions = Array.isArray(task.suggestions) ? task.suggestions : [];

    let inputHtml;
    if (isChoice && options.length) {
      inputHtml = `<div class="choices" role="group">${options
        .map(
          (opt, i) =>
            `<label class="choice"><input type="${isMulti ? "checkbox" : "radio"}" name="choice" value="${escapeAttr(opt)}" data-choice /> ${escapeHtml(opt)}</label>`,
        )
        .join("")}</div>`;
    } else if (fieldType === "text_multi") {
      inputHtml = `<textarea id="answer" rows="4">${escapeHtml(task.ocr_text || "")}</textarea>`;
    } else {
      inputHtml = `<input id="answer" type="text" value="${escapeAttr(task.ocr_text || "")}" autocomplete="off" />`;
    }

    const visionText = task.ocr_vision_text || "";
    const visionHtml = visionText
      ? `<div class="ocr-box">
          <strong>Vision候補（AI読取）</strong>
          <div>${escapeHtml(visionText)}</div>
        </div>`
      : "";

    const suggestHtml = suggestions.length
      ? `<div class="suggest"><div class="meta">補正候補（過去の確定・入力値）</div>
          <div class="suggest-btns">${suggestions
            .map(
              (s) =>
                `<button type="button" class="chip" data-suggest="${escapeAttr(s)}">${escapeHtml(s)}</button>`,
            )
            .join("")}</div></div>`
      : "";

    root.innerHTML = `
      <h1>${escapeHtml(task.name || "項目チェック")}</h1>
      <p class="meta">画像を見て、${isChoice ? "当てはまる選択肢を選んで" : "読み取れる文字を入力して"}ください。OCR候補は参考です。</p>
      <div class="card">
        <img class="crop" alt="対象領域" src="${task.image_url || `/public/api/image/${task.token}`}" />
        <div class="ocr-box">
          <strong>${visionText ? "OCR候補（PP-OCR）" : "OCR候補"}</strong>
          <div>${escapeHtml(task.ocr_text || "（なし）")}</div>
          <div class="meta">信頼度: ${Number(task.ocr_confidence || 0).toFixed(2)}</div>
        </div>
        ${visionHtml}
        <label>${isChoice ? "選択" : "読み取り結果"}</label>
        ${inputHtml}
        ${suggestHtml}
        <label class="meta" style="font-weight:500">
          <input type="checkbox" id="blank" /> 空欄（記入なし）
        </label>
        <label class="meta" style="font-weight:500">
          <input type="checkbox" id="unreadable" /> 判読不能
        </label>
        <div class="actions">
          <button class="btn" id="submit" type="button">送信する</button>
          ${isChoice ? "" : `<button class="btn secondary" id="use-ocr" type="button">${visionText ? "PP-OCR候補を採用" : "OCR候補を採用"}</button>`}
          ${isChoice || !visionText ? "" : '<button class="btn secondary" id="use-vision" type="button">Vision候補を採用</button>'}
        </div>
        <p id="msg" class="error" hidden></p>
      </div>`;

    const answer = document.getElementById("answer");
    const unreadable = document.getElementById("unreadable");
    const blank = document.getElementById("blank");
    const msg = document.getElementById("msg");
    const choiceInputs = Array.from(root.querySelectorAll("[data-choice]"));

    const applyDisabled = () => {
      const off = unreadable.checked || blank.checked;
      if (answer) answer.disabled = off;
      choiceInputs.forEach((el) => {
        el.disabled = off;
      });
    };

    const getValue = () => {
      if (isChoice) {
        const picked = choiceInputs
          .filter((el) => el.checked)
          .map((el) => el.value);
        return isMulti ? picked.join(MULTI_SEP) : picked[0] || "";
      }
      return answer ? answer.value : "";
    };
    const setValue = (v) => {
      if (isChoice) {
        const set = isMulti ? parseMulti(v) : [v];
        choiceInputs.forEach((el) => {
          el.checked = set.includes(el.value);
        });
      } else if (answer) {
        answer.value = v;
      }
    };

    const useOcr = document.getElementById("use-ocr");
    if (useOcr) {
      useOcr.addEventListener("click", () => {
        setValue(task.ocr_text || "");
        unreadable.checked = false;
        blank.checked = false;
        applyDisabled();
      });
    }
    const useVision = document.getElementById("use-vision");
    if (useVision) {
      useVision.addEventListener("click", () => {
        setValue(task.ocr_vision_text || "");
        unreadable.checked = false;
        blank.checked = false;
        applyDisabled();
      });
    }
    root.querySelectorAll("[data-suggest]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const s = btn.getAttribute("data-suggest") || "";
        if (isMulti) {
          const set = parseMulti(getValue());
          const idx = set.indexOf(s);
          if (idx >= 0) set.splice(idx, 1);
          else set.push(s);
          setValue(set.join(MULTI_SEP));
        } else {
          setValue(s);
        }
      });
    });
    unreadable.addEventListener("change", () => {
      if (unreadable.checked) blank.checked = false;
      applyDisabled();
    });
    blank.addEventListener("change", () => {
      if (blank.checked) unreadable.checked = false;
      applyDisabled();
    });
    document.getElementById("submit").addEventListener("click", async () => {
      msg.hidden = true;
      const body = {
        answer_text: getValue(),
        is_unreadable: unreadable.checked,
        is_blank: blank.checked,
        checker_key: getCheckerKey(),
      };
      const r = await fetch(`/public/api/task/${encodeURIComponent(task.token)}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        msg.hidden = false;
        msg.textContent = j.error || "送信に失敗しました";
        return;
      }
      bumpScore();
      renderDone("送信しました。ご協力ありがとうございます。");
    });
  };

  const escapeHtml = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const escapeAttr = (s) => escapeHtml(s).replace(/'/g, "&#39;");

  const boot = async () => {
    renderScore();
    getCheckerKey();
    const token = tokenFromPath();
    if (!token) {
      renderError("トークンがありません");
      return;
    }
    try {
      const r = await fetch(`/public/api/task/${encodeURIComponent(token)}`);
      const j = await r.json();
      if (!r.ok) {
        renderError(j.error || "タスクを取得できませんでした");
        return;
      }
      renderTask(j);
    } catch {
      renderError("通信エラーが発生しました");
    }
  };

  // 公開トップの「次のチェック」用（index からも呼ばれる）
  window.doccheckClaimNext = claimNext;
  boot();
})();
