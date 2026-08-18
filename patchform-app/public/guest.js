/* ゲスト回答 UI。描画する type はサーバ catalog（enabled のみ）と一致させる。 */
(function () {
  const root = document.getElementById("root");
  const token = location.pathname.split("/public/f/")[1] || "";
  let pin = "";

  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const show = (html) => {
    root.innerHTML = html;
  };

  const api = async (path, opts) => {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || "通信に失敗しました");
    }
    return data;
  };

  const fieldHtml = (c) => {
    const req = c.required ? '<span class="req">必須</span>' : "";
    const ph = esc(c.placeholder || "");
    const opts = (c.properties && c.properties.options) || [];
    if (c.type === "textarea") {
      return `<label for="${esc(c.id)}">${esc(c.label)}${req}</label><textarea id="${esc(c.id)}" name="${esc(c.id)}" rows="4" placeholder="${ph}"></textarea>`;
    }
    if (c.type === "select") {
      const items = opts
        .map((o) => `<option value="${esc(o)}">${esc(o)}</option>`)
        .join("");
      return `<label for="${esc(c.id)}">${esc(c.label)}${req}</label><select id="${esc(c.id)}" name="${esc(c.id)}"><option value="">選択してください</option>${items}</select>`;
    }
    if (c.type === "radio") {
      const items = opts
        .map(
          (o, i) =>
            `<label><input type="radio" name="${esc(c.id)}" value="${esc(o)}" /> ${esc(o)}</label>`,
        )
        .join("");
      return `<fieldset><legend>${esc(c.label)}${req}</legend><div class="choices">${items}</div></fieldset>`;
    }
    if (c.type === "checkbox") {
      const items = opts
        .map(
          (o) =>
            `<label><input type="checkbox" name="${esc(c.id)}" value="${esc(o)}" /> ${esc(o)}</label>`,
        )
        .join("");
      return `<fieldset><legend>${esc(c.label)}${req}</legend><div class="choices">${items}</div></fieldset>`;
    }
    if (c.type === "address_composite") {
      return `<fieldset><legend>${esc(c.label)}${req}</legend>
        <label>郵便番号</label><input name="${esc(c.id)}.postal_code" type="text" />
        <label>都道府県</label><input name="${esc(c.id)}.prefecture" type="text" />
        <label>市区町村</label><input name="${esc(c.id)}.city" type="text" />
        <label>町名・番地</label><input name="${esc(c.id)}.street" type="text" />
        <label>建物名</label><input name="${esc(c.id)}.building" type="text" /></fieldset>`;
    }
    if (c.type === "user_info_composite") {
      return `<fieldset><legend>${esc(c.label)}${req}</legend>
        <label>姓</label><input name="${esc(c.id)}.last_name" type="text" />
        <label>名</label><input name="${esc(c.id)}.first_name" type="text" />
        <label>セイ</label><input name="${esc(c.id)}.last_name_kana" type="text" />
        <label>メイ</label><input name="${esc(c.id)}.first_name_kana" type="text" /></fieldset>`;
    }
    if (c.type === "company_info_composite") {
      return `<fieldset><legend>${esc(c.label)}${req}</legend>
        <label>法人名</label><input name="${esc(c.id)}.company_name" type="text" />
        <label>法人番号</label><input name="${esc(c.id)}.corporate_number" type="text" />
        <label>代表者</label><input name="${esc(c.id)}.representative" type="text" /></fieldset>`;
    }
    if (c.type === "financial_institution_composite") {
      return `<fieldset><legend>${esc(c.label)}${req}</legend>
        <label>金融機関名</label><input name="${esc(c.id)}.bank_name" type="text" />
        <label>支店名</label><input name="${esc(c.id)}.branch_name" type="text" />
        <label>口座種別</label><input name="${esc(c.id)}.account_type" type="text" />
        <label>口座番号</label><input name="${esc(c.id)}.account_number" type="text" />
        <label>口座名義</label><input name="${esc(c.id)}.account_holder" type="text" /></fieldset>`;
    }
    if (c.type === "calculated") {
      return `<p>${esc(c.label)}は送信時に自動計算されます。</p>`;
    }
    if (c.type === "text_display") {
      return `<p class="desc">${esc((c.properties && c.properties.text) || c.label)}</p>`;
    }
    if (c.type === "image_display") {
      const src = (c.properties && c.properties.src) || "";
      const safe =
        /^https?:\/\//i.test(src) || String(src).indexOf("data:image/") === 0 ? src : "";
      return safe
        ? `<p>${esc(c.label)}</p><img alt="${esc(c.label)}" src="${esc(safe)}" />`
        : `<p class="desc">${esc(c.label)}（画像未設定）</p>`;
    }
    if (c.type === "divider" || c.type === "page_break") {
      return `<hr />`;
    }
    if (c.type === "location") {
      return `<fieldset><legend>${esc(c.label)}${req}</legend>
        <button type="button" data-loc="${esc(c.id)}">現在地を取得</button>
        <label>緯度</label><input name="${esc(c.id)}.lat" type="text" inputmode="decimal" />
        <label>経度</label><input name="${esc(c.id)}.lng" type="text" inputmode="decimal" /></fieldset>`;
    }
    if (c.type === "image_recognition" || c.type === "document_reader") {
      const accept = c.type === "image_recognition" ? "image/*" : "";
      return `<label>${esc(c.label)}${req}</label>
        <input name="${esc(c.id)}.file" type="file" ${accept ? `accept="${accept}"` : ""} data-extract="${c.type === "image_recognition" ? "image" : "document"}" />
        <textarea name="${esc(c.id)}.extracted" rows="4" placeholder="読み取った内容（自動読取できない場合は手入力）"></textarea>`;
    }
    if (c.type === "daterange") {
      return `<label>${esc(c.label)}${req}</label><input name="${esc(c.id)}.start" type="date" /> 〜 <input name="${esc(c.id)}.end" type="date" />`;
    }
    if (c.type === "slider") {
      return `<label>${esc(c.label)}${req}</label><input name="${esc(c.id)}" type="range" min="0" max="100" />`;
    }
    if (c.type === "rating") {
      return `<label>${esc(c.label)}${req}</label><input name="${esc(c.id)}" type="number" min="1" max="5" />`;
    }
    if (c.type === "matrix_question") {
      const rows = (c.properties && c.properties.rows) || [];
      const cols = (c.properties && c.properties.columns) || [];
      const head = cols.map((col) => `<th>${esc(col)}</th>`).join("");
      const body = rows
        .map(
          (row) =>
            `<tr><td>${esc(row)}</td>${cols
              .map((col) => `<td><input type="radio" name="${esc(c.id)}.${esc(row)}" value="${esc(col)}" /></td>`)
              .join("")}</tr>`,
        )
        .join("");
      return `<fieldset><legend>${esc(c.label)}${req}</legend><table><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></fieldset>`;
    }
    const type =
      c.type === "email"
        ? "email"
        : c.type === "phone"
          ? "tel"
          : c.type === "number"
            ? "number"
            : c.type === "date"
              ? "date"
              : c.type === "time"
                ? "time"
                : c.type === "datetime-local"
                  ? "datetime-local"
                  : c.type === "password"
                    ? "password"
                    : c.type === "file" || c.type === "signature_pad"
                      ? "file"
                      : c.type === "mynumber"
                        ? "text"
                        : "text";
    const extra = c.type === "mynumber" ? ' inputmode="numeric" maxlength="12"' : "";
    return `<label for="${esc(c.id)}">${esc(c.label)}${req}</label><input id="${esc(c.id)}" name="${esc(c.id)}" type="${type}" placeholder="${ph}"${extra} />`;
  };

  const readDataUrl = (file) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });

  const collect = async (form, components) => {
    const answers = {};
    for (const c of components) {
      if (
        c.type === "text_display" ||
        c.type === "image_display" ||
        c.type === "divider" ||
        c.type === "page_break" ||
        c.type === "calculated"
      ) {
        continue;
      } else if (c.type === "daterange") {
        answers[c.id] = {
          start: (form.querySelector(`[name="${c.id}.start"]`) || {}).value || "",
          end: (form.querySelector(`[name="${c.id}.end"]`) || {}).value || "",
        };
      } else if (c.type === "location") {
        answers[c.id] = {
          lat: (form.querySelector(`[name="${c.id}.lat"]`) || {}).value || "",
          lng: (form.querySelector(`[name="${c.id}.lng"]`) || {}).value || "",
        };
      } else if (c.type === "image_recognition" || c.type === "document_reader") {
        const fileEl = form.querySelector(`[name="${c.id}.file"]`);
        const extracted = (form.querySelector(`[name="${c.id}.extracted"]`) || {}).value || "";
        const file = fileEl && fileEl.files && fileEl.files[0];
        answers[c.id] = { filename: file ? file.name : "", extracted };
      } else if (c.type === "matrix_question") {
        const obj = {};
        for (const el of form.querySelectorAll(`[name^="${c.id}."]`)) {
          if (el.checked) obj[el.name.slice(c.id.length + 1)] = el.value;
        }
        answers[c.id] = obj;
      } else if (c.type.endsWith("_composite")) {
        const obj = {};
        for (const el of form.querySelectorAll(`[name^="${c.id}."]`)) {
          obj[el.name.slice(c.id.length + 1)] = el.value;
        }
        answers[c.id] = obj;
      } else if (c.type === "checkbox") {
        answers[c.id] = Array.from(
          form.querySelectorAll(`input[name="${c.id}"]:checked`),
        ).map((el) => el.value);
      } else if (c.type === "radio") {
        const el = form.querySelector(`input[name="${c.id}"]:checked`);
        answers[c.id] = el ? el.value : "";
      } else if (c.type === "file") {
        const el = form.querySelector(`[name="${c.id}"]`);
        answers[c.id] = el && el.files && el.files[0] ? el.files[0].name : "";
      } else if (c.type === "signature_pad") {
        const el = form.querySelector(`[name="${c.id}"]`);
        answers[c.id] = el && el.files && el.files[0] ? await readDataUrl(el.files[0]) : "";
      } else if (c.type === "slider" || c.type === "rating") {
        const el = form.querySelector(`[name="${c.id}"]`);
        answers[c.id] = el && el.value !== "" ? Number(el.value) : "";
      } else {
        const el = form.querySelector(`[name="${c.id}"]`);
        answers[c.id] = el ? el.value : "";
      }
    }
    return answers;
  };

  const renderForm = (data) => {
    document.title = data.title || "フォーム";
    const comps = (data.definition && data.definition.components) || [];
    show(`
      <h1>${esc(data.title)}</h1>
      <p class="desc">${esc(data.description || "")}</p>
      <form id="pf">
        <label for="submitter_name">お名前（任意）</label>
        <input id="submitter_name" name="submitter_name" type="text" />
        ${comps.map(fieldHtml).join("")}
        <p class="error" id="err" hidden></p>
        <button type="submit">送信する</button>
      </form>
    `);
    document.querySelectorAll("[data-loc]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!navigator.geolocation) return;
        const cid = btn.getAttribute("data-loc");
        navigator.geolocation.getCurrentPosition((pos) => {
          const lat = document.querySelector(`[name="${cid}.lat"]`);
          const lng = document.querySelector(`[name="${cid}.lng"]`);
          if (lat) lat.value = String(pos.coords.latitude);
          if (lng) lng.value = String(pos.coords.longitude);
        });
      });
    });
    document.querySelectorAll("[data-extract]").forEach((el) => {
      el.addEventListener("change", async () => {
        const file = el.files && el.files[0];
        if (!file) return;
        const kind = el.getAttribute("data-extract");
        const name = el.getAttribute("name") || "";
        const cid = name.replace(/\.file$/, "");
        const dest = document.querySelector(`[name="${cid}.extracted"]`);
        try {
          const data = await readDataUrl(file);
          const res = await api("/public/api/extract", {
            method: "POST",
            body: JSON.stringify({ kind, filename: file.name, data }),
          });
          if (dest) dest.value = res.extracted || dest.value;
        } catch (_err) {
          /* 手入力 */
        }
      });
    });
    const formatVal = (c, v) => {
      if (c.type === "password") return v ? "••••" : "（未入力）";
      if (c.type === "signature_pad") return v ? "（署名あり）" : "（未入力）";
      if (v == null || v === "") return "（未入力）";
      if (Array.isArray(v)) return v.join("、") || "（未入力）";
      if (typeof v === "object") {
        if (v.start || v.end) return `${v.start || "—"} 〜 ${v.end || "—"}`;
        if (v.lat != null && v.lng != null) return `${v.lat}, ${v.lng}`;
        if (v.extracted != null || v.filename != null) {
          return [v.filename, v.extracted].filter(Boolean).join(" / ") || "（未入力）";
        }
        return Object.entries(v)
          .filter(([, x]) => x != null && x !== "")
          .map(([k, x]) => `${k}: ${x}`)
          .join("、") || "（未入力）";
      }
      return String(v);
    };

    const sendAnswers = async (submitterName, answers) => {
      const result = await api(`/public/api/forms/${encodeURIComponent(token)}/submissions`, {
        method: "POST",
        body: JSON.stringify({
          pin,
          submitter_name: submitterName,
          answers,
        }),
      });
      show(
        `<div class="receipt"><h1>受け付けました</h1><p>控え番号: <strong>${esc(result.receipt_code)}</strong></p><p>この番号を控えてください。</p></div>`,
      );
    };

    document.getElementById("pf").addEventListener("submit", async (e) => {
      e.preventDefault();
      const formEl = e.target;
      const errEl = document.getElementById("err");
      errEl.hidden = true;
      try {
        const submitterName = document.getElementById("submitter_name").value;
        const answers = await collect(formEl, comps);
        const rows = comps
          .filter(
            (c) =>
              !["text_display", "image_display", "divider", "page_break", "calculated"].includes(
                c.type,
              ),
          )
          .map(
            (c) =>
              `<div class="row"><dt>${esc(c.label)}</dt><dd>${esc(formatVal(c, answers[c.id]))}</dd></div>`,
          )
          .join("");
        formEl.hidden = true;
        let confirm = document.getElementById("pf-confirm");
        if (confirm) confirm.remove();
        confirm = document.createElement("div");
        confirm.id = "pf-confirm";
        confirm.innerHTML = `
          <h2>内容の確認</h2>
          <p class="desc">この内容で送信してよろしいですか。</p>
          ${submitterName ? `<p>お名前: ${esc(submitterName)}</p>` : ""}
          <dl class="confirm">${rows}</dl>
          <p class="error" id="confirm-err" hidden></p>
          <button type="button" id="pf-back">修正する</button>
          <button type="button" id="pf-ok">送信する</button>
        `;
        formEl.after(confirm);
        document.getElementById("pf-back").addEventListener("click", () => {
          confirm.remove();
          formEl.hidden = false;
        });
        document.getElementById("pf-ok").addEventListener("click", async () => {
          const cErr = document.getElementById("confirm-err");
          cErr.hidden = true;
          try {
            await sendAnswers(submitterName, answers);
          } catch (err) {
            cErr.textContent = err.message;
            cErr.hidden = false;
          }
        });
      } catch (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
      }
    });
  };

  const renderPin = (data) => {
    document.title = data.title || "フォーム";
    show(`
      <h1>${esc(data.title || "フォーム")}</h1>
      <p class="desc">暗証番号を入力してください。</p>
      <form id="pin-form">
        <label for="pin">暗証番号（4桁）</label>
        <input id="pin" name="pin" inputmode="numeric" maxlength="4" required />
        <p class="error" id="err" hidden></p>
        <button type="submit">開く</button>
      </form>
    `);
    document.getElementById("pin-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = document.getElementById("err");
      errEl.hidden = true;
      pin = document.getElementById("pin").value;
      try {
        const unlocked = await api(`/public/api/forms/${encodeURIComponent(token)}`, {
          method: "POST",
          body: JSON.stringify({ pin }),
        });
        if (unlocked.requires_pin) {
          throw new Error("暗証番号が正しくありません");
        }
        renderForm(unlocked);
      } catch (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
      }
    });
  };

  const start = async () => {
    if (!token) {
      show("<p class='error'>リンクが不正です。</p>");
      return;
    }
    try {
      const data = await api(`/public/api/forms/${encodeURIComponent(token)}`);
      if (data.requires_pin) renderPin(data);
      else renderForm(data);
    } catch (err) {
      show(`<p class="error">${esc(err.message)}</p>`);
    }
  };

  start();
})();
