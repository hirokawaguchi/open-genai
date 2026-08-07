(function () {
  const root = document.getElementById("root");
  const parts = location.pathname.split("/").filter(Boolean);
  // /public/e/{token}
  const tokenIdx = parts.indexOf("e");
  const token = tokenIdx >= 0 ? parts[tokenIdx + 1] : "";

  if (!token) {
    root.innerHTML = "<p class='error'>共有リンクが不正です。</p>";
    return;
  }

  const statusLabel = { ok: "参加可", maybe: "検討中", ng: "不可" };
  const statusMark = { ok: "○", maybe: "△", ng: "×" };

  function fmtDate(iso, end, allDay) {
    try {
      const d = new Date(iso);
      const opts = allDay
        ? { year: "numeric", month: "short", day: "numeric", weekday: "short" }
        : {
            year: "numeric",
            month: "short",
            day: "numeric",
            weekday: "short",
            hour: "2-digit",
            minute: "2-digit",
          };
      let s = d.toLocaleString("ja-JP", opts);
      if (end && !allDay) {
        const e = new Date(end);
        s +=
          " 〜 " +
          e.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
      }
      return s;
    } catch {
      return iso;
    }
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function participantsOf(data) {
    const names = [];
    const seen = new Set();
    for (const r of data.responses || []) {
      if (!seen.has(r.participant_name)) {
        seen.add(r.participant_name);
        names.push(r.participant_name);
      }
    }
    return names;
  }

  function answerMap(data) {
    // name -> { dateId -> status }
    const map = {};
    for (const r of data.responses || []) {
      if (!map[r.participant_name]) map[r.participant_name] = {};
      map[r.participant_name][r.event_date_id] = r.status;
    }
    return map;
  }

  function matrixHtml(data) {
    const dates = data.dates || [];
    const names = participantsOf(data);
    const answers = answerMap(data);

    if (dates.length === 0) {
      return "<p class='hint'>日程候補がありません。</p>";
    }

    const headNames = names
      .map(function (n) {
        return '<th class="col-person">' + esc(n) + "</th>";
      })
      .join("");

    const body = dates
      .map(function (d) {
        const st = (data.statistics && data.statistics[String(d.id)]) || {};
        const personCells = names
          .map(function (n) {
            const status = answers[n] && answers[n][d.id];
            const mark = status ? statusMark[status] : "—";
            const cls = status ? "mark mark-" + status : "mark mark-empty";
            return (
              '<td class="col-person ' +
              cls +
              '" title="' +
              esc(status ? statusLabel[status] : "未回答") +
              '">' +
              mark +
              "</td>"
            );
          })
          .join("");
        return (
          "<tr><th scope='row' class='col-date'>" +
          esc(fmtDate(d.date_time, d.end_time, d.is_all_day)) +
          (d.is_all_day ? "（終日）" : "") +
          "</th>" +
          '<td class="col-sum">' +
          (st.ok || 0) +
          "</td>" +
          '<td class="col-sum">' +
          (st.maybe || 0) +
          "</td>" +
          '<td class="col-sum">' +
          (st.ng || 0) +
          "</td>" +
          personCells +
          "</tr>"
        );
      })
      .join("");

    return (
      '<div class="matrix-wrap">' +
      '<table class="matrix">' +
      "<thead><tr>" +
      '<th class="col-date">日程</th>' +
      '<th class="col-sum" title="参加可">○</th>' +
      '<th class="col-sum" title="検討中">△</th>' +
      '<th class="col-sum" title="不可">×</th>' +
      headNames +
      "</tr></thead><tbody>" +
      body +
      "</tbody></table></div>" +
      (names.length === 0
        ? "<p class='hint'>まだ回答がありません。下のフォームから回答できます。</p>"
        : "")
    );
  }

  async function load() {
    const res = await fetch("/public/api/events/" + encodeURIComponent(token));
    const data = await res.json();
    if (!res.ok) {
      root.innerHTML =
        "<p class='error'>" + esc(data.error || "読み込みに失敗しました") + "</p>";
      return;
    }
    render(data);
  }

  function render(data) {
    const ev = data.event;
    const dates = data.dates || [];
    const names = participantsOf(data);
    document.title = ev.title + " · 日程調整";

    let dateRows = dates
      .map((d) => {
        return (
          '<div class="row" data-date-id="' +
          d.id +
          '">' +
          '<div class="date-label">' +
          esc(fmtDate(d.date_time, d.end_time, d.is_all_day)) +
          (d.is_all_day ? "（終日）" : "") +
          "</div>" +
          '<div class="statuses">' +
          ["ok", "maybe", "ng"]
            .map(
              (st) =>
                "<label><input type='radio' name='st-" +
                d.id +
                "' value='" +
                st +
                "' /> " +
                statusMark[st] +
                " " +
                statusLabel[st] +
                "</label>"
            )
            .join("") +
          "</div></div>"
        );
      })
      .join("");

    root.innerHTML =
      "<h1>" +
      esc(ev.title) +
      "</h1>" +
      "<p class='hint'>回答者" +
      names.length +
      "名</p>" +
      (ev.creator_name
        ? "<p class='hint'>作成者: " + esc(ev.creator_name) + "</p>"
        : "") +
      (ev.description
        ? "<p class='meta'>" + esc(ev.description) + "</p>"
        : "") +
      "<div class='card stats'><h2 style='margin-top:0;font-size:1.1rem'>日程候補・回答一覧</h2>" +
      "<p class='hint'>行が日程、列が回答者です。○参加可 / △検討中 / ×不可</p>" +
      matrixHtml(data) +
      "</div>" +
      "<div class='card'><h2 style='margin-top:0;font-size:1.1rem'>出欠を入力する</h2>" +
      "<label for='name'>お名前</label>" +
      "<input id='name' type='text' autocomplete='name' />" +
      "<label for='pin'>暗証番号（4桁）</label>" +
      "<input id='pin' type='password' inputmode='numeric' maxlength='4' autocomplete='off' />" +
      "<p class='hint'>初回は暗証番号を設定します。再回答・削除時に同じ番号が必要です。</p>" +
      dateRows +
      "<p id='msg' class='error' style='display:none'></p>" +
      "<div style='margin-top:1rem;display:flex;gap:0.5rem;flex-wrap:wrap'>" +
      "<button type='button' id='submit'>回答を送信</button>" +
      "<button type='button' class='secondary' id='reload'>再読み込み</button>" +
      "</div></div>";

    document.getElementById("reload").onclick = load;
    document.getElementById("submit").onclick = async function () {
      const name = document.getElementById("name").value.trim();
      const pin = document.getElementById("pin").value.trim();
      const msg = document.getElementById("msg");
      msg.style.display = "none";
      if (!name) {
        msg.textContent = "お名前を入力してください";
        msg.style.display = "block";
        return;
      }
      const responses = dates.map((d) => {
        const checked = document.querySelector(
          'input[name="st-' + d.id + '"]:checked'
        );
        return {
          event_date_id: d.id,
          status: checked ? checked.value : "ng",
        };
      });
      const res = await fetch(
        "/public/api/events/" + encodeURIComponent(token) + "/responses",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            participant_name: name,
            password: pin,
            responses: responses,
          }),
        }
      );
      const body = await res.json();
      if (!res.ok) {
        msg.textContent = body.error || "送信に失敗しました";
        msg.style.display = "block";
        return;
      }
      await load();
      alert(body.message || "送信しました");
    };
  }

  load().catch(function (e) {
    root.innerHTML =
      "<p class='error'>読み込みに失敗しました: " + esc(String(e)) + "</p>";
  });
})();
