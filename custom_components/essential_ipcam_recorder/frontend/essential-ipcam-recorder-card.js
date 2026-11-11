/*
 * Essential IP Cam Recorder card
 * Shows the latest camera events of several media folders in one timeline:
 * newest event large with inline video, below a list grouped by day.
 * Without "sources" in the config, the cameras of the integration are used.
 *
 * Dateinamen: YYYY-MM-DD_HH-mm-ss_[KENNUNG].jpg (+ gleichnamige .mp4)
 *             ältere Schreibweise YYYY-MM-DD_HH-mm-ss_kennung.jpg wird ebenfalls erkannt
 * Ordner:     <Quelle>/<Tagesordner, z. B. 2026_10_29>/<Datei> oder direkt <Quelle>/<Datei>
 * Favoriten:  <Quelle>/<Favoritenordner>/<Datei>, verschoben über essential_ipcam_recorder.toggle_favorite
 */

const VERSION = "0.1.1-beta.4";
const KEC_DOMAIN = "essential_ipcam_recorder";
const KEC_TAG = "essential-ipcam-recorder-card";

const KEC_DEFAULTS = {
  title: "",
  max_items: 10,
  refresh_interval: 30,
  thumbnail_width: 144,
  thumbnail_max_width: 320,
  entry_spacing: 24,
  show_filters: true,
  show_camera_filter: true,
  default_type: "PERSON",
  default_camera: "",
  favorites_folder: "Favorites",
  sources: [],
  types: {
    PERSON: { icon: "mdi:account", color: "#f5b54a" },
    PET: { icon: "mdi:paw", color: "#6fd1c6" },
    MOTION: { icon: "mdi:motion-sensor", color: "#c5d1d7" },
  },
};

const KEC_TEXT = {
  en: {
    type_PERSON: "Person", type_PET: "Pet", type_MOTION: "Motion", event: "Event",
    all: "All", all_cameras: "All cameras", load_more: "Load more", loading: "Loading events …",
    no_events: "No events found.", no_cameras: "No cameras configured.", load_error: "Error while loading",
    video: "Video", play: "Play video", video_error: "Video could not be loaded", close: "Close",
    fav_add: "Add to favorites", fav_remove: "Remove favorite", fav_error: "Favorite could not be changed",
    f_title: "Title (optional)", f_max_items: "Events per page", f_thumbnail_width: "Thumbnails: minimum width",
    f_thumbnail_max_width: "Thumbnails: maximum width (wide cards)", f_entry_spacing: "Spacing between entries",
    f_refresh_interval: "Refresh interval", f_show_filters: "Show type filter", f_show_camera_filter: "Show camera filter",
    f_default_type: "Initial type filter", f_default_camera: "Initial camera filter",
    f_favorites_folder: "Favorites folder (custom sources only)", f_sources: "Custom sources (empty = recorder cameras)",
    f_types: "Event types (label: name, icon, color)",
  },
  de: {
    type_PERSON: "Person", type_PET: "Tier", type_MOTION: "Bewegung", event: "Event",
    all: "Alle", all_cameras: "Alle Kameras", load_more: "Mehr laden", loading: "Lade Events …",
    no_events: "Keine Events gefunden.", no_cameras: "Keine Kameras eingerichtet.", load_error: "Fehler beim Laden",
    video: "Video", play: "Video abspielen", video_error: "Video konnte nicht geladen werden", close: "Schließen",
    fav_add: "Als Favorit markieren", fav_remove: "Favorit entfernen", fav_error: "Favorit konnte nicht geändert werden",
    f_title: "Titel (optional)", f_max_items: "Events pro Seite", f_thumbnail_width: "Vorschaubilder: Mindestbreite",
    f_thumbnail_max_width: "Vorschaubilder: Maximalbreite (breite Karten)", f_entry_spacing: "Abstand zwischen Einträgen",
    f_refresh_interval: "Aktualisierung", f_show_filters: "Typ-Filter anzeigen", f_show_camera_filter: "Kamera-Filter anzeigen",
    f_default_type: "Start-Filter Typ", f_default_camera: "Start-Filter Kamera",
    f_favorites_folder: "Favoriten-Ordner (nur bei eigenen Quellen)", f_sources: "Eigene Quellen (leer = Kameras der Integration)",
    f_types: "Eventtypen (Kennung: name, icon, color)",
  },
};

function kecT(hass, key) {
  const sprache = String((hass && ((hass.locale && hass.locale.language) || hass.language)) || "en").split("-")[0];
  return (KEC_TEXT[sprache] || KEC_TEXT.en)[key] || KEC_TEXT.en[key] || key;
}

const KEC_UNBEKANNT = { name: "Event", icon: "mdi:cctv", color: "var(--secondary-text-color)" };
const KEC_URL_GUELTIGKEIT = 3600; // Sekunden, wie lange eine signierte Medien-URL gilt
const KEC_URL_NEU_NACH = 50 * 60 * 1000; // ms, ab wann eine gespeicherte URL neu geholt wird

const KEC_BILD = /\.(jpe?g|png)$/i;
const KEC_VIDEO = /\.mp4$/i;
const KEC_ZEIT = /(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/;

function kecVersteckt(titel) {
  return /^[@._]/.test(titel);
}

function kecZeitstempel(name) {
  const m = name.match(KEC_ZEIT);
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
}

function kecKennung(stamm) {
  let m = stamm.match(/\[([^\]]+)\]\s*$/);
  if (m) return m[1].trim().toUpperCase();
  m = stamm.match(/_([A-Za-z]+)$/);
  return m ? m[1].toUpperCase() : "";
}

function kecEl(tag, attrs = {}, kinder = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kind of [].concat(kinder)) if (kind) el.append(kind);
  return el;
}

/* Lädt Tagesordner aller Quellen schrittweise, neueste zuerst. */
class KecLader {
  constructor(hass, quellen, favoritenOrdner) {
    this.hass = hass;
    this.favoritenOrdner = favoritenOrdner;
    this._favOrdner = (src) => (src.favorites_folder === undefined ? this.favoritenOrdner : src.favorites_folder);
    this.quellen = quellen.map((src) => ({ src, tage: null, idx: 0 }));
    this.items = [];
    this.ids = new Set();
  }

  _browse(id) {
    return this.hass.callWS({ type: "media_source/browse_media", media_content_id: id });
  }

  _hinzufuegen(kinder, src, fav = false) {
    const videos = new Map();
    for (const k of kinder) {
      if (!k.can_expand && KEC_VIDEO.test(k.title)) videos.set(k.title.replace(KEC_VIDEO, ""), k.media_content_id);
    }
    for (const k of kinder) {
      if (k.can_expand || !KEC_BILD.test(k.title) || this.ids.has(k.media_content_id)) continue;
      const stamm = k.title.replace(KEC_BILD, "");
      const ts = kecZeitstempel(stamm);
      if (ts === null) continue;
      this.ids.add(k.media_content_id);
      this.items.push({
        id: k.media_content_id,
        ts,
        quelle: src.name,
        src,
        fav,
        kennung: kecKennung(stamm),
        bild: k.media_content_id,
        video: videos.get(stamm) || null,
      });
    }
  }

  get moeglich() {
    return this.quellen.some((q) => q.tage === null || q.idx < q.tage.length);
  }

  gefiltert(filter) {
    const f = filter || {};
    let liste = this.items.filter((e) => (!f.typ || e.kennung === f.typ) && (!f.quelle || e.quelle === f.quelle));
    if (this.moeglich) {
      // Favoriten erst zeigen, wenn die Tage bis zu ihrem Datum geladen sind (sonst Lücken im Verlauf)
      const normal = this.items.filter((e) => !e.fav);
      let grenze = Infinity;
      if (normal.length) {
        const d = new Date(Math.min(...normal.map((e) => e.ts)));
        d.setHours(0, 0, 0, 0);
        grenze = d.getTime();
      }
      liste = liste.filter((e) => !e.fav || e.ts >= grenze);
    }
    return liste;
  }

  async ladeBis(anzahl, filter) {
    for (const q of this.quellen) {
      if (q.tage !== null) continue;
      const wurzel = await this._browse(q.src.path);
      const kinder = wurzel.children || [];
      this._hinzufuegen(kinder, q.src);
      const favName = this._favOrdner(q.src);
      const favOrdner = favName && kinder.find((k) => k.can_expand && k.title === favName);
      if (favOrdner) {
        const inhalt = await this._browse(favOrdner.media_content_id);
        this._hinzufuegen(inhalt.children || [], q.src, true);
      }
      q.tage = kinder
        .filter((k) => k.can_expand && !kecVersteckt(k.title) && k.title !== favName)
        .sort((a, b) => b.title.localeCompare(a.title));
    }
    while (this.gefiltert(filter).length < anzahl) {
      // nächster Tag über alle Quellen, gleiche Tage gemeinsam laden
      let tag = null;
      for (const q of this.quellen) {
        if (q.idx < q.tage.length && (tag === null || q.tage[q.idx].title > tag)) tag = q.tage[q.idx].title;
      }
      if (tag === null) break;
      const jobs = [];
      for (const q of this.quellen) {
        if (q.idx < q.tage.length && q.tage[q.idx].title === tag) {
          const ordner = q.tage[q.idx++];
          jobs.push(this._browse(ordner.media_content_id).then((r) => this._hinzufuegen(r.children || [], q.src)));
        }
      }
      await Promise.all(jobs);
    }
    this.items.sort((a, b) => b.ts - a.ts);
  }
}

class KameraEventCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement(`${KEC_TAG}-editor`);
  }

  static getStubConfig() {
    return {
      max_items: KEC_DEFAULTS.max_items,
      refresh_interval: KEC_DEFAULTS.refresh_interval,
      thumbnail_width: KEC_DEFAULTS.thumbnail_width,
      thumbnail_max_width: KEC_DEFAULTS.thumbnail_max_width,
      show_filters: true,
    };
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    if (config.sources !== undefined && !Array.isArray(config.sources)) {
      throw new Error('"sources" must be a list of { name, path }.');
    }
    for (const s of config.sources || []) {
      if (!s || !s.name || !s.path) throw new Error('Every source needs "name" and "path".');
    }
    const types = {};
    for (const [k, v] of Object.entries(KEC_DEFAULTS.types)) types[k] = { ...v };
    for (const [k, v] of Object.entries(config.labels || {})) {
      types[k.toUpperCase()] = { ...(types[k.toUpperCase()] || KEC_UNBEKANNT), name: String(v) };
    }
    for (const [k, v] of Object.entries(config.types || {})) {
      types[k.toUpperCase()] = { ...(types[k.toUpperCase()] || KEC_UNBEKANNT), ...(v || {}) };
    }
    this._config = { ...KEC_DEFAULTS, ...config, types };
    this._eigeneQuellen = Array.isArray(config.sources) && config.sources.length > 0;
    this._quellen = this._eigeneQuellen ? config.sources : null;
    this._limit = Number(this._config.max_items) || 10;
    const typStart = String(this._config.default_type || "").toUpperCase();
    const quelleStart = String(this._config.default_camera || "");
    this._filter = {
      typ: this._config.types[typStart] ? typStart : null,
      quelle: quelleStart || null,
    };
    this._lader = null;
    this._heroId = null;
    this._signatur = null;
    if (!this._card) this._aufbauen();
    this._card.header = this._config.title || undefined;
    const minB = Number(this._config.thumbnail_width) || 144;
    this.style.setProperty("--kec-thumb-w", `${minB}px`);
    this.style.setProperty("--kec-abstand", `${Math.max(0, Number(this._config.entry_spacing ?? 24))}px`);
    this.style.setProperty("--kec-thumb-max", `${Math.max(minB, Number(this._config.thumbnail_max_width) || 320)}px`);
    this._timerNeu();
    if (this._hass) this._aktualisieren(true);
  }

  set hass(hass) {
    const erstes = !this._hass;
    this._hass = hass;
    if (erstes && this._mehrEl) this._mehrEl.textContent = this._t("load_more");
    if (erstes && this._config) this._aktualisieren(true);
  }

  connectedCallback() {
    this._timerNeu();
    if (this._hass && this._config) this._aktualisieren(true);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
  }

  getCardSize() {
    return 4 + (Number(this._config && this._config.max_items) || 10);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _t(key) {
    return kecT(this._hass, key);
  }

  _typ(kennung) {
    const typ = this._config.types[kennung];
    if (typ) return { ...typ, name: typ.name || this._t(`type_${kennung}`) };
    return { ...KEC_UNBEKANNT, name: kennung || this._t("event") };
  }

  _timerNeu() {
    clearInterval(this._timer);
    this._timer = null;
    if (!this._config || !this.isConnected) return;
    const sek = Math.max(5, Number(this._config.refresh_interval) || 30);
    this._timer = setInterval(() => this._aktualisieren(true), sek * 1000);
  }

  _aufbauen() {
    const root = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      :host { --kec-thumb-w: 144px; --kec-thumb-max: 320px; --kec-abstand: 24px; }
      ha-card { overflow: hidden; display: flex; flex-direction: column; container-type: inline-size; }
      .filter { display: flex; flex-direction: column; gap: 8px; padding: 12px 16px; }
      .filterzeile { display: flex; flex-wrap: wrap; gap: 8px; }
      .chipbtn {
        height: 32px; padding: 0 14px; border-radius: 16px; cursor: pointer;
        border: 1px solid var(--divider-color, #3a3a3a); background: transparent;
        color: var(--primary-text-color); font: inherit; font-size: 13px; font-weight: 500;
      }
      .chipbtn.aktiv { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
      .hero-media {
        position: relative; width: 100%; aspect-ratio: 16 / 9; overflow: hidden;
        background: var(--secondary-background-color, #2b2f31); border: 0; padding: 0; display: block; cursor: pointer;
      }
      .hero-media img, .hero-media video { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
      .hero-play {
        position: absolute; right: 12px; bottom: 12px; width: 56px; height: 56px; border-radius: 50%;
        border: 0; background: rgba(0, 0, 0, 0.6); color: #fff; cursor: pointer;
        display: flex; align-items: center; justify-content: center; --mdc-icon-size: 34px;
      }
      .hero-info { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px 16px; }
      .hero-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
      .hero-quelle { font-size: 20px; font-weight: 500; }
      .sek { font-size: 14px; color: var(--secondary-text-color); }
      .typchip {
        display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 12px; border-radius: 14px; flex-shrink: 0;
        color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent);
        font-size: 13px; font-weight: 500; --mdc-icon-size: 16px;
      }
      .trenner { height: 1px; background: var(--divider-color, #2c2c2c); margin: 0 16px; }
      .tag {
        padding: 14px 16px 6px; font-size: 12px; font-weight: 700; letter-spacing: 0.08em;
        text-transform: uppercase; color: var(--secondary-text-color);
      }
      .zeile {
        display: flex; align-items: center; gap: 16px; width: 100%; padding: calc(var(--kec-abstand) / 2) 16px; min-height: 64px; box-sizing: border-box;
        border: 0; background: transparent; color: inherit; text-align: left; font: inherit; cursor: pointer;
      }
      .zeile:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
      .thumb {
        position: relative; width: clamp(var(--kec-thumb-w), 32cqw, var(--kec-thumb-max)); aspect-ratio: 16 / 9; flex-shrink: 0; border-radius: 8px; overflow: hidden;
        background: var(--secondary-background-color, #2b2f31);
      }
      .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
      @container (min-width: 500px) {
        .thumb { width: clamp(var(--kec-thumb-w), 45cqw, var(--kec-thumb-max)); }
      }
      .badge {
        position: absolute; right: 4px; bottom: 4px; display: inline-flex; align-items: center; gap: 2px;
        padding: 1px 6px 1px 3px; border-radius: 4px; background: rgba(0, 0, 0, 0.7); color: #fff;
        font-size: 11px; font-weight: 500; --mdc-icon-size: 14px;
      }
      .typicon { color: var(--c); --mdc-icon-size: 22px; flex-shrink: 0; }
      .zeile-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
      .zeile-titel { font-size: 15px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .zeile-zeit { font-size: 13px; color: var(--secondary-text-color); }
      .mehr {
        align-self: center; height: 44px; margin: 8px 0 12px; padding: 0 20px; border-radius: 22px; cursor: pointer;
        border: 1px solid var(--divider-color, #3a3a3a); background: transparent;
        color: var(--primary-color); font: inherit; font-size: 14px; font-weight: 500;
      }
      .mehr[disabled] { opacity: 0.5; cursor: default; }
      .status { padding: 16px; color: var(--secondary-text-color); }
      .hero-wrap, .zeile-wrap { position: relative; }
      .stern {
        position: absolute; z-index: 1; width: 32px; height: 32px; border-radius: 50%; padding: 0;
        border: 0; background: rgba(0, 0, 0, 0.55); color: #fff; cursor: pointer;
        display: flex; align-items: center; justify-content: center; --mdc-icon-size: 20px;
      }
      .stern.aktiv { color: #f5c542; }
      .stern[disabled] { opacity: 0.5; cursor: progress; }
      .hero-wrap .stern { left: 12px; top: 12px; width: 40px; height: 40px; --mdc-icon-size: 24px; }
      .zeile-wrap .stern { left: 20px; top: calc(var(--kec-abstand) / 2 + 4px); }
    `;
    this._card = kecEl("ha-card");
    this._filterEl = kecEl("div", { class: "filter" });
    this._heroEl = kecEl("div");
    this._listeEl = kecEl("div");
    this._mehrEl = kecEl("button", { class: "mehr", text: kecT(null, "load_more"), onclick: () => this._mehr() });
    this._statusEl = kecEl("div", { class: "status", text: kecT(null, "loading") });
    this._card.append(this._filterEl, this._heroEl, this._listeEl, this._mehrEl, this._statusEl);
    root.append(style, this._card);
    this._urls = new Map();
  }

  async _url(id, frisch = false) {
    const c = this._urls.get(id);
    if (!frisch && c && Date.now() - c.at < KEC_URL_NEU_NACH) return c.url;
    const r = await this._hass.callWS({ type: "media_source/resolve_media", media_content_id: id, expires: KEC_URL_GUELTIGKEIT });
    const url = this._hass.hassUrl(r.url);
    this._urls.set(id, { url, at: Date.now() });
    return url;
  }

  /* Video-Quelle setzen. Holt die signierte URL frisch und erneuert sie, wenn sie
     beim Abspielen alt ist oder das Video hängen bleibt (abgelaufene Signatur). */
  async _videoAnbinden(video, id) {
    let geholt = 0;
    let versuche = 0;
    let haenger = null;
    const setzen = async (weiterspielen) => {
      const t = video.currentTime || 0;
      const url = await this._url(id, true);
      geholt = Date.now();
      if (t > 0 || weiterspielen) {
        video.addEventListener("loadedmetadata", () => {
          if (t > 0) video.currentTime = t;
          if (weiterspielen) video.play().catch(() => {});
        }, { once: true });
      }
      video.src = url;
    };
    const erneuern = () => {
      if (versuche >= 3) return;
      versuche += 1;
      setzen(true).catch(() => {});
    };
    video.addEventListener("error", erneuern);
    video.addEventListener("waiting", () => {
      clearTimeout(haenger);
      haenger = setTimeout(erneuern, 6000);
    });
    for (const n of ["playing", "pause", "seeked", "ended"]) {
      video.addEventListener(n, () => {
        clearTimeout(haenger);
        if (n === "playing") versuche = 0;
      });
    }
    video.addEventListener("play", () => {
      if (Date.now() - geholt > 20000) setzen(true).catch(() => {});
    });
    await setzen(false);
  }

  _heroSpielt() {
    return !!(this._heroVideo && !this._heroVideo.paused && !this._heroVideo.ended);
  }

  async _holeQuellen() {
    if (this._eigeneQuellen) return this._quellen;
    if (!this._quellen || !this._quellenZeit || Date.now() - this._quellenZeit > 5 * 60 * 1000) {
      this._quellen = await this._hass.callWS({ type: `${KEC_DOMAIN}/cameras` });
      this._quellenZeit = Date.now();
    }
    return this._quellen;
  }

  async _aktualisieren(neu, erzwingen = false) {
    if (!this._hass || !this._config || this._laedt) return;
    this._laedt = true;
    try {
      const quellen = await this._holeQuellen();
      if (!quellen.length) {
        this._statusEl.style.display = "";
        this._statusEl.textContent = this._t("no_cameras");
        return;
      }
      const lader = neu || !this._lader ? new KecLader(this._hass, quellen, this._config.favorites_folder) : this._lader;
      await lader.ladeBis(this._limit + 1, this._filter);
      this._lader = lader;
      await this._zeichnen(erzwingen);
    } catch (err) {
      this._statusEl.style.display = "";
      this._statusEl.textContent = `${this._t("load_error")}: ${err && err.message ? err.message : err}`;
    } finally {
      this._laedt = false;
    }
  }

  _mehr() {
    this._limit += Number(this._config.max_items) || 10;
    this._mehrEl.disabled = true;
    this._aktualisieren(false, true);
  }

  _filtern(aenderung) {
    this._filter = { ...this._filter, ...aenderung };
    this._limit = Number(this._config.max_items) || 10;
    this._aktualisieren(false, true);
  }

  async _zeichnen(erzwingen = false) {
    const alle = this._lader.gefiltert(this._filter);
    const liste = alle.slice(0, this._limit);
    const signatur = `${this._filter.typ}/${this._filter.quelle}|${liste.map((e) => `${e.id}${e.video ? "+" : ""}${e.fav ? "*" : ""}`).join(";")}|${this._lader.moeglich || alle.length > liste.length}`;
    if (signatur === this._signatur) return;
    if (!erzwingen && this._heroSpielt() && (!liste[0] || liste[0].id !== this._heroId)) {
      this._nachholen = true; // neues Event, aber oben läuft gerade ein Video
      return;
    }
    const urls = await Promise.all(liste.map((e) => this._url(e.bild).catch(() => null)));
    this._signatur = signatur;
    this._nachholen = false;

    this._zeichneFilter();
    if (liste.length === 0) {
      this._heroEl.replaceChildren();
      this._heroId = null;
      this._heroStoppen();
      this._listeEl.replaceChildren();
      this._mehrEl.style.display = "none";
      this._statusEl.style.display = "";
      this._statusEl.textContent = this._t("no_events");
      return;
    }
    this._statusEl.style.display = "none";
    if (liste[0].id !== this._heroId) this._zeichneHero(liste[0], urls[0]);
    this._zeichneListe(liste.slice(1), urls.slice(1));
    const mehrMoeglich = this._lader.moeglich || alle.length > liste.length;
    this._mehrEl.style.display = mehrMoeglich ? "" : "none";
    this._mehrEl.disabled = false;
  }

  _zeichneFilter() {
    const typAus = this._config.show_filters === false;
    const quellen = this._quellen || [];
    const kameraAus = this._config.show_camera_filter === false || quellen.length < 2;
    this._filterEl.style.display = typAus && kameraAus ? "none" : "";
    const chip = (text, aktiv, aenderung) => kecEl("button", {
      class: `chipbtn${aktiv ? " aktiv" : ""}`,
      text,
      "aria-pressed": String(aktiv),
      onclick: () => this._filtern(aenderung),
    });
    const zeilen = [];
    if (!kameraAus) {
      const k = [chip(this._t("all_cameras"), !this._filter.quelle, { quelle: null })];
      for (const q of quellen) k.push(chip(q.name, this._filter.quelle === q.name, { quelle: q.name }));
      zeilen.push(kecEl("div", { class: "filterzeile", role: "group", "aria-label": "Kamera" }, k));
    }
    if (!typAus) {
      const t = [chip(this._t("all"), !this._filter.typ, { typ: null })];
      for (const kennung of Object.keys(this._config.types)) t.push(chip(this._typ(kennung).name, this._filter.typ === kennung, { typ: kennung }));
      zeilen.push(kecEl("div", { class: "filterzeile", role: "group", "aria-label": "Eventtyp" }, t));
    }
    this._filterEl.replaceChildren(...zeilen);
  }

  _datum(ts) {
    const sprache = (this._hass.locale && this._hass.locale.language) || this._hass.language || "de";
    const d = new Date(ts);
    return {
      datum: d.toLocaleDateString(sprache, { day: "2-digit", month: "2-digit", year: "numeric" }),
      zeit: d.toLocaleTimeString(sprache, { hour: "2-digit", minute: "2-digit" }),
      sprache,
    };
  }

  _wann(ts) {
    const { datum, zeit } = this._datum(ts);
    return `${datum} · ${zeit}`;
  }

  _tagTitel(ts) {
    const { sprache } = this._datum(ts);
    const heute = new Date();
    heute.setHours(0, 0, 0, 0);
    const tag = new Date(ts);
    tag.setHours(0, 0, 0, 0);
    const diff = Math.round((tag - heute) / 86400000);
    if (diff === 0 || diff === -1) {
      const t = new Intl.RelativeTimeFormat(sprache, { numeric: "auto" }).format(diff, "day");
      return t.charAt(0).toUpperCase() + t.slice(1);
    }
    return tag.toLocaleDateString(sprache, { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
  }

  _typChip(typ) {
    const chip = kecEl("span", { class: "typchip" }, [kecEl("ha-icon", { icon: typ.icon }), kecEl("span", { text: typ.name })]);
    chip.style.setProperty("--c", typ.color);
    return chip;
  }

  _kannFavorit(e) {
    const fav = e.src && (e.src.favorites_folder === undefined ? this._config.favorites_folder : e.src.favorites_folder);
    return !!(fav && this._hass.services && this._hass.services[KEC_DOMAIN]);
  }

  _stern(e) {
    if (!this._kannFavorit(e)) return null;
    const btn = kecEl("button", {
      class: `stern${e.fav ? " aktiv" : ""}`,
      "aria-pressed": String(!!e.fav),
      "aria-label": this._t(e.fav ? "fav_remove" : "fav_add"),
      title: this._t(e.fav ? "fav_remove" : "fav_add"),
    }, [kecEl("ha-icon", { icon: e.fav ? "mdi:star" : "mdi:star-outline" })]);
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._favoritUmschalten(e, btn);
    });
    return btn;
  }

  async _favoritUmschalten(e, btn) {
    btn.disabled = true;
    try {
      await this._hass.callService(KEC_DOMAIN, "toggle_favorite", { media_content_id: e.bild });
      this._signatur = null;
      await this._aktualisieren(true, true);
    } catch (err) {
      btn.disabled = false;
      this.dispatchEvent(new CustomEvent("hass-notification", {
        detail: { message: `${this._t("fav_error")}: ${err && err.message ? err.message : err}` },
        bubbles: true,
        composed: true,
      }));
    }
  }

  _heroStoppen() {
    if (this._heroVideo) {
      this._heroVideo.pause();
      this._heroVideo.removeAttribute("src");
      this._heroVideo.load();
    }
    this._heroVideo = null;
  }

  _zeichneHero(e, bildUrl) {
    const typ = this._typ(e.kennung);
    this._heroId = e.id;
    this._heroStoppen();
    const medien = kecEl("div", { class: "hero-media" });
    if (bildUrl) medien.append(kecEl("img", { src: bildUrl, alt: `${e.quelle}: ${typ.name}` }));
    if (e.video) {
      const start = (ev) => {
        ev.stopPropagation();
        this._heroAbspielen(e, bildUrl, medien);
      };
      medien.append(kecEl("button", { class: "hero-play", "aria-label": this._t("play"), onclick: start }, [
        kecEl("ha-icon", { icon: "mdi:play" }),
      ]));
      medien.addEventListener("click", start);
    } else {
      medien.addEventListener("click", () => this._oeffnen(e, bildUrl));
    }
    const info = kecEl("div", { class: "hero-info" }, [
      kecEl("div", { class: "hero-text" }, [
        kecEl("span", { class: "hero-quelle", text: e.quelle }),
        kecEl("span", { class: "sek", text: this._wann(e.ts) }),
      ]),
      this._typChip(typ),
    ]);
    const wrap = kecEl("div", { class: "hero-wrap" }, [medien, this._stern(e)]);
    this._heroEl.replaceChildren(wrap, info, kecEl("div", { class: "trenner" }));
  }

  async _heroAbspielen(e, bildUrl, medien) {
    if (this._heroVideo) return;
    try {
      const video = kecEl("video", { controls: true, playsinline: true, preload: "auto", poster: bildUrl || undefined });
      await this._videoAnbinden(video, e.video);
      this._heroVideo = video;
      const weiter = () => { if (this._nachholen) this._zeichnen(); };
      video.addEventListener("pause", weiter);
      video.addEventListener("ended", weiter);
      medien.replaceChildren(video);
      medien.style.cursor = "default";
      await video.play().catch(() => {
        video.muted = true;
        return video.play().catch(() => {});
      });
    } catch (err) {
      this._oeffnen(e, bildUrl);
    }
  }

  _zeichneListe(liste, urls) {
    const teile = [];
    let letzterTag = null;
    liste.forEach((e, i) => {
      const tag = this._tagTitel(e.ts);
      if (tag !== letzterTag) {
        teile.push(kecEl("div", { class: "tag", text: tag }));
        letzterTag = tag;
      }
      const typ = this._typ(e.kennung);
      const titel = `${e.quelle}: ${typ.name}`;
      const thumb = kecEl("div", { class: "thumb" }, [
        urls[i] ? kecEl("img", { src: urls[i], alt: "", loading: "lazy" }) : null,
        e.video ? kecEl("span", { class: "badge" }, [kecEl("ha-icon", { icon: "mdi:play" }), kecEl("span", { text: this._t("video") })]) : null,
      ]);
      const icon = kecEl("ha-icon", { class: "typicon", icon: typ.icon });
      icon.style.setProperty("--c", typ.color);
      const zeile = kecEl("button", { class: "zeile", "aria-label": `${titel}, ${this._wann(e.ts)}`, onclick: () => this._oeffnen(e, urls[i]) }, [
        thumb,
        icon,
        kecEl("div", { class: "zeile-text" }, [
          kecEl("span", { class: "zeile-titel", text: titel }),
          kecEl("span", { class: "zeile-zeit", text: this._wann(e.ts) }),
        ]),
      ]);
      teile.push(kecEl("div", { class: "zeile-wrap" }, [zeile, this._stern(e)]));
    });
    this._listeEl.replaceChildren(...teile);
  }

  async _oeffnen(e, bildUrl) {
    if (this._heroVideo && !this._heroVideo.paused) this._heroVideo.pause();
    const typ = this._typ(e.kennung);
    const overlay = kecEl("div");
    overlay.setAttribute(
      "style",
      "position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.9);display:flex;flex-direction:column;" +
        "align-items:center;justify-content:center;padding:16px;box-sizing:border-box;gap:12px;"
    );
    const text = kecEl("span", { text: `${e.quelle}: ${typ.name} · ${this._wann(e.ts)}` });
    const zu = kecEl("button", { "aria-label": this._t("close"), text: "✕" });
    zu.setAttribute("style", "background:none;border:0;color:#fff;font-size:22px;cursor:pointer;width:44px;height:44px;");
    const kopf = kecEl("div", {}, [text, zu]);
    kopf.setAttribute("style", "color:#fff;font-family:Roboto,system-ui,sans-serif;font-size:16px;display:flex;gap:16px;align-items:center;max-width:100%;");
    let medium;
    if (e.video) {
      medium = kecEl("video", { controls: true, playsinline: true, preload: "auto", poster: bildUrl || undefined });
    } else {
      medium = kecEl("img", { src: bildUrl || undefined, alt: text.textContent });
    }
    medium.setAttribute("style", "max-width:100%;max-height:calc(100% - 64px);border-radius:8px;background:#000;");
    overlay.append(kopf, medium);

    const taste = (ev) => { if (ev.key === "Escape") schliessen(); };
    const schliessen = () => {
      if (medium.pause) medium.pause();
      document.removeEventListener("keydown", taste);
      overlay.remove();
    };
    zu.addEventListener("click", schliessen);
    overlay.addEventListener("click", (ev) => { if (ev.target === overlay) schliessen(); });
    document.addEventListener("keydown", taste);
    document.body.append(overlay);

    if (e.video) {
      try {
        await this._videoAnbinden(medium, e.video);
        await medium.play().catch(() => {
          medium.muted = true;
          return medium.play().catch(() => {});
        });
      } catch (err) {
        text.textContent = `${this._t("video_error")}: ${err && err.message ? err.message : err}`;
      }
    }
  }
}

const KEC_SCHEMA = [
  { name: "title", selector: { text: {} } },
  { name: "max_items", selector: { number: { min: 1, max: 50, mode: "box" } } },
  { name: "thumbnail_width", selector: { number: { min: 60, max: 400, mode: "box", unit_of_measurement: "px" } } },
  { name: "thumbnail_max_width", selector: { number: { min: 60, max: 600, mode: "box", unit_of_measurement: "px" } } },
  { name: "entry_spacing", selector: { number: { min: 0, max: 64, mode: "box", unit_of_measurement: "px" } } },
  { name: "refresh_interval", selector: { number: { min: 5, max: 600, mode: "box", unit_of_measurement: "s" } } },
  { name: "show_filters", selector: { boolean: {} } },
  { name: "show_camera_filter", selector: { boolean: {} } },
  { name: "default_type", selector: { text: {} } },
  { name: "default_camera", selector: { text: {} } },
  { name: "favorites_folder", selector: { text: {} } },
  { name: "sources", selector: { object: {} } },
  { name: "types", selector: { object: {} } },
];


class KameraEventCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._zeichnen();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _zeichnen() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => kecT(this._hass, `f_${s.name}`);
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this._config = ev.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.append(this._form);
    }
    this._form.hass = this._hass;
    const c = this._config || {};
    const typen = Object.keys({ ...KEC_DEFAULTS.types, ...(c.types || {}) });
    const kameras = (Array.isArray(c.sources) ? c.sources : []).map((q) => q && q.name).filter(Boolean);
    this._form.schema = KEC_SCHEMA.map((f) => {
      if (f.name === "default_type") {
        return { name: f.name, selector: { select: { mode: "dropdown", options: [{ value: "", label: kecT(this._hass, "all") }, ...typen.map((t) => ({ value: t, label: t }))] } } };
      }
      if (f.name === "default_camera") {
        return { name: f.name, selector: { select: { mode: "dropdown", options: [{ value: "", label: kecT(this._hass, "all_cameras") }, ...kameras.map((k) => ({ value: k, label: k }))] } } };
      }
      return f;
    });
    this._form.data = { ...KEC_DEFAULTS, types: undefined, sources: undefined, ...this._config };
  }
}

if (!customElements.get(KEC_TAG)) customElements.define(KEC_TAG, KameraEventCard);
if (!customElements.get(`${KEC_TAG}-editor`)) customElements.define(`${KEC_TAG}-editor`, KameraEventCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === KEC_TAG)) {
  window.customCards.push({
    type: KEC_TAG,
    name: "Essential IP Cam Recorder",
    description: "Latest camera events of all recorder cameras in one timeline with inline video.",
    preview: false,
  });
}

console.info(`%c ESSENTIAL-IPCAM-RECORDER-CARD %c ${VERSION} `, "background:#03a9f4;color:#fff", "");
