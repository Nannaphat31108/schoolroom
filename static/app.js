(() => {
  const pageHasLiveMonitor = document.body.hasAttribute('data-live-bookings');
  let checkingLiveStatus = false;
  let pollTimer = null;

  const localActiveIds = () => new Set(
    [...document.querySelectorAll('[data-active-booking-id]')]
      .map((el) => Number(el.dataset.activeBookingId))
      .filter(Number.isFinite)
  );

  const localActiveRooms = () => new Set(
    [...document.querySelectorAll('[data-active-room-key]')]
      .map((el) => el.dataset.activeRoomKey)
      .filter(Boolean)
  );

  const setsEqual = (a, b) => {
    if (a.size !== b.size) return false;
    for (const value of a) if (!b.has(value)) return false;
    return true;
  };

  async function checkLiveStatus(forceReloadAtRelease = false) {
    if (!pageHasLiveMonitor || checkingLiveStatus || document.hidden) return;
    checkingLiveStatus = true;
    try {
      const baseLiveUrl = document.body.dataset.liveUrl || '/api/live-bookings';
      const liveUrl = `${baseLiveUrl}${baseLiveUrl.includes('?') ? '&' : '?'}_=${Date.now()}`;
      const response = await fetch(liveUrl, {
        method: 'GET',
        cache: 'no-store',
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data || !data.ok) return;

      let changed = false;

      const idNodes = document.querySelectorAll('[data-active-booking-id]');
      if (idNodes.length) {
        const serverIds = new Set((data.active_ids || []).map(Number));
        changed = changed || !setsEqual(localActiveIds(), serverIds);
      }

      const roomNodes = document.querySelectorAll('[data-active-room-key]');
      if (roomNodes.length) {
        const serverRooms = new Set(data.active_rooms || []);
        // หน้ารายห้องแสดงเพียงอาคารเดียว จึงตรวจเฉพาะห้องที่อยู่บนหน้านี้
        // ไม่เทียบจำนวนกับทั้งโรงเรียน เพื่อไม่ให้ reload วนเมื่ออาคารอื่นมีการจอง
        for (const roomKey of localActiveRooms()) {
          if (!serverRooms.has(roomKey)) {
            changed = true;
            break;
          }
        }
      }

      const countNode = document.querySelector('[data-active-booking-count]');
      if (countNode) {
        changed = changed || Number(countNode.dataset.activeBookingCount) !== Number(data.active_count);
      }

      // เมื่อ timer จุดสิ้นสุดเป็นคนเรียก ให้ reload หลัง server ยืนยันสถานะเสมอ
      // เพื่อให้ห้องเปลี่ยนจาก "ไม่ว่าง" เป็น "ว่าง" โดยไม่ค้าง UI เดิม
      if (changed || forceReloadAtRelease) {
        window.location.reload();
      }
    } catch (_) {
      // เน็ตสะดุดชั่วคราวไม่ทำให้หน้าเว็บพัง รอบ poll ถัดไปจะลองใหม่
    } finally {
      checkingLiveStatus = false;
    }
  }

  // ตั้ง timer ตรงเวลาสิ้นสุดที่ใกล้ที่สุด แต่แทนที่จะ reload แบบเดิม
  // ให้ถาม server ก่อน เพื่อ sync database และสถานะจริง
  const releaseTimers = [...document.querySelectorAll('[data-auto-release-ms]')]
    .map((el) => Number(el.dataset.autoReleaseMs))
    .filter((ms) => Number.isFinite(ms) && ms > 0);

  if (releaseTimers.length) {
    const nearest = Math.min(...releaseTimers);
    window.setTimeout(() => checkLiveStatus(true), Math.max(500, nearest + 500));
  }

  // fallback สำหรับ browser ที่ throttle setTimeout ตอนพักแท็บ
  // 3 วินาทีเป็น request JSON เล็ก ๆ และใส่ cache-buster เพื่อให้ Render/Browser ส่งถึง backend จริง
  if (pageHasLiveMonitor) {
    pollTimer = window.setInterval(() => checkLiveStatus(false), 3000);
    window.setTimeout(() => checkLiveStatus(false), 1000);

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) checkLiveStatus(false);
    });

    window.addEventListener('pageshow', () => checkLiveStatus(false));
  }

  const dialog = document.getElementById('confirmDialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  let pendingForm = null;
  document.querySelectorAll('[data-confirm-cancel]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (form.dataset.confirmed === '1') return;
      event.preventDefault();
      pendingForm = form;
      dialog.showModal();
    });
  });

  dialog.querySelector('[data-dialog-close]')?.addEventListener('click', () => {
    pendingForm = null;
    dialog.close();
  });

  dialog.querySelector('[data-dialog-confirm]')?.addEventListener('click', () => {
    if (!pendingForm) return dialog.close();
    pendingForm.dataset.confirmed = '1';
    dialog.close();
    pendingForm.requestSubmit();
  });

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      pendingForm = null;
      dialog.close();
    }
  });
})();
