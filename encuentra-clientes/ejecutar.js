#!/usr/bin/env node
// Ejecuta el flujo n8n "Encuentra clientes · Prospectos con demo y primer mensaje" fuera de n8n.
// Los nodos Code van copiados tal cual del flujo; los nodos de n8n se simulan así:
//   Busca en Google Maps -> Places API si hay GOOGLE_MAPS_API_KEY; si no, lugares.js (mismo formato)
//   Lee su web           -> curl (si la web no responde, el nodo sigue con error, igual que onError: continue)
//   Califica con IA / Escribe el primer mensaje -> calificacion.json / mensajes.json (salida del modelo, mismo orden)
//   Guarda en Prospectos -> Prospectos.csv + Prospectos.xlsx (mismas columnas que la hoja)
// Uso: node ejecutar.js   (se corre por etapas: genera senales.json, luego elegidos.json, luego la hoja)
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const D = __dirname;
const lee = (f) => (fs.existsSync(path.join(D, f)) ? JSON.parse(fs.readFileSync(path.join(D, f), 'utf8')) : null);
const guarda = (f, v) => fs.writeFileSync(path.join(D, f), JSON.stringify(v, null, 2));

// ---- Formulario "Busca clientes" + "Tus datos"
const formulario = {
  nicho: process.env.NICHO || 'dentista',
  // CIUDAD='' cuando cada zona ya trae su ciudad ("Polanco, Ciudad de México")
  ciudad: process.env.CIUDAD ?? 'Guadalajara, Jalisco',
  zonas: process.env.ZONAS || 'Providencia\nChapultepec\nZapopan Centro',
  cuantos: Number(process.env.CUANTOS || 20),
};
const n8nUrl = String(process.env.N8N_URL || '').replace(/\/+$/, '');
const tusDatos = {
  ...formulario,
  tuNombre: process.env.TU_NOMBRE || 'Marcelo',
  demoUrl: n8nUrl ? `${n8nUrl}/webhook/demo-recepcionista` : '',
  idioma: 'es',
  region: 'MX',
  maxInvestigar: 200,
};

const salidas = { 'Tus datos': [tusDatos] };
const nodo = (nombre) => ({
  first: () => ({ json: salidas[nombre][0] }),
  all: () => salidas[nombre].map((json) => ({ json })),
});
const $ = nodo;
const corre = (fn, entrada) => fn($, { all: () => entrada.map((json) => ({ json })) }).map((i) => i.json);

// ---- Arma las búsquedas
const armaLasBusquedas = ($, $input) => {
  const f = $('Tus datos').first().json;
  const limpia = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
  const nicho = limpia(f.nicho) || 'dentista';
  const ciudad = limpia(f.ciudad);
  const vistas = new Set();
  const zonas = String(f.zonas ?? '')
    .split(/[\n;]+/)
    .map(limpia)
    .filter((z) => {
      const clave = z.toLowerCase();
      if (!z || vistas.has(clave)) return false;
      vistas.add(clave);
      return true;
    })
    .slice(0, 30);
  const consultas = zonas.length ? zonas.map((z) => `${nicho} en ${z}${ciudad ? ', ' + ciudad : ''}`) : [`${nicho} en ${ciudad}`];
  return consultas.map((textQuery) => ({ json: { textQuery } }));
};

// ---- Junta las clínicas
const juntaLasClinicas = ($, $input) => {
  const cfg = $('Tus datos').first().json;
  const maximo = Math.max(1, Math.min(500, Number(cfg.maxInvestigar) || 200));
  const corta = (s, n) => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, n);
  const SOCIAL = /^(https?:\/\/)?([a-z0-9-]+\.)*(facebook\.com|fb\.com|instagram\.com|linktr\.ee|wa\.me|whatsapp\.com|tiktok\.com|twitter\.com|x\.com|youtube\.com|google\.com|business\.site|g\.page)(\/|$)/i;
  const vistos = new Set();
  const out = [];
  for (const { json: respuesta } of $input.all()) {
    for (const p of Array.isArray(respuesta.places) ? respuesta.places : []) {
      if (!p || !p.id || vistos.has(p.id)) continue;
      if (p.businessStatus && p.businessStatus !== 'OPERATIONAL') continue;
      vistos.add(p.id);
      const web = /^https?:\/\//i.test(String(p.websiteUri ?? '')) ? String(p.websiteUri).trim() : '';
      const social = !!web && SOCIAL.test(web);
      out.push({
        json: {
          placeId: p.id,
          nombre: corta(p.displayName?.text, 100),
          direccion: corta(p.formattedAddress, 200),
          telefono: corta(p.internationalPhoneNumber || p.nationalPhoneNumber, 30),
          web,
          social,
          webParaLeer: social ? '' : web,
          maps: String(p.googleMapsUri ?? ''),
          rating: Number(p.rating) || 0,
          total: Number(p.userRatingCount) || 0,
          horario: p.regularOpeningHours && typeof p.regularOpeningHours === 'object' ? p.regularOpeningHours : null,
          resenas: (Array.isArray(p.reviews) ? p.reviews : [])
            .map((r) => ({
              estrellas: Number(r.rating) || 0,
              hace: corta(r.relativePublishTimeDescription, 40),
              texto: corta(r.originalText?.text || r.text?.text, 1200),
            }))
            .filter((r) => r.texto),
        },
      });
      if (out.length >= maximo) return out;
    }
  }
  return out;
};

// ---- Señales
const senales = ($, $input) => {
  const cfg = $('Tus datos').first().json;
  const lugares = $('Junta las clínicas').all().map((i) => i.json);
  const webs = $input.all().map((i) => i.json);
  const corta = (s, n) => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, n);

  const ENTIDADES = { nbsp: ' ', amp: '&', quot: '"', apos: "'", lt: '<', gt: '>', aacute: 'á', eacute: 'é', iacute: 'í', oacute: 'ó', uacute: 'ú', ntilde: 'ñ', uuml: 'ü', Aacute: 'Á', Eacute: 'É', Iacute: 'Í', Oacute: 'Ó', Uacute: 'Ú', Ntilde: 'Ñ', iexcl: '¡', iquest: '¿' };
  const caracter = (n) => (n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : ' ');
  const textoVisible = (html) =>
    String(html)
      .replace(/<(script|style|noscript|svg|template)\b[\s\S]*?<\/\1>/gi, ' ')
      .replace(/<!--[\s\S]*?-->/g, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&#(\d+);/g, (_, n) => caracter(Number(n)))
      .replace(/&#x([0-9a-f]+);/gi, (_, n) => caracter(parseInt(n, 16)))
      .replace(/&([a-z]+);/gi, (m, n) => ENTIDADES[n] ?? m)
      .replace(/\s+/g, ' ')
      .trim();

  const CHATS = [
    ['Tawk.to', /embed\.tawk\.to/i], ['Tidio', /code\.tidio\.co/i], ['Crisp', /client\.crisp\.chat/i], ['Intercom', /widget\.intercom\.io|intercomcdn\.com/i],
    ['Zendesk', /static\.zdassets\.com|zopim/i], ['LiveChat', /cdn\.livechatinc\.com/i], ['JivoChat', /code\.jivosite\.com|jivochat/i], ['Smartsupp', /smartsuppchat\.com/i],
    ['HubSpot', /js\.usemessages\.com/i], ['ManyChat', /manychat\.com/i], ['Botpress', /botpress/i], ['Landbot', /landbot\.io/i], ['Chatbase', /chatbase\.co/i],
    ['n8n', /@n8n\/chat/i], ['Drift', /js\.driftt\.com/i], ['Freshchat', /wchat\.freshchat\.com/i], ['Kommo', /kommo\.com/i], ['Callbell', /callbell\.eu/i],
    ['Wati', /wati\.io/i], ['Respond.io', /respond\.io/i], ['Leadsales', /leadsales\.io/i], ['Olark', /static\.olark\.com/i], ['Userlike', /userlike-cdn|userlike\.com/i],
    ['Messenger', /xfbml\.customerchat/i],
  ];
  const AGENDA = /doctoralia|docplanner|calendly\.com|agendapro|cal\.com\/|reservo\.cl|simplybook|setmore|acuityscheduling|booksy|fresha\.com|youcanbook|dentalink|(agenda|reserva)r?\s+(tu\s+|su\s+|una\s+)?cita\s+en\s+l[ií]nea|(agenda|reserva)\s+en\s+l[ií]nea/i;
  const WA = /(?:wa\.me\/|api\.whatsapp\.com\/send\/?\?(?:[^"'\s>]*?&(?:amp;)?)?phone=|whatsapp\.com\/send\?phone=)\+?(\d{8,15})/i;
  const QUEJAS = [
    /\b(no|nunca|jam[aá]s|nadie)\b[^.,;!?\n]{0,20}?\b(contest|respond)\w*/i,
    /\b(no|nunca|jam[aá]s|nadie)\s+(me\s+|nos\s+|les\s+|te\s+)?atiend\w*\s+(el\s+|los\s+|la\s+|las\s+|al\s+)?(tel[eé]fono|whats\w*|mensajes?|llamadas?|celular)/i,
    /\bno\s+(me\s+|nos\s+|te\s+)?(regres|devolv|devuelv)\w*\s+(la\s+|las\s+)?llamadas?/i,
    /sin\s+respuesta|dej\w*\s+en\s+visto|imposible\s+(comunicar|contactar|localizar)|dif[ií]cil\s+(comunicar|contactar)|tardan?\w*\s+[^.,;!?\n]{0,25}?(contestar|responder)/i,
  ];
  const frases = (t) => String(t).split(/(?<=[.!?¡¿…])\s+|\n+/).map((f) => f.trim()).filter(Boolean);
  const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
  const leeHorario = (oh) => {
    const periodos = Array.isArray(oh?.periods) ? oh.periods : [];
    if (!periodos.length) return { cierraMin: null, abreDomingo: null, siempre: false };
    const p0 = periodos[0];
    if (periodos.length === 1 && p0.open && p0.open.day === 0 && !(p0.open.hour ?? 0) && !(p0.open.minute ?? 0) && !p0.close) {
      return { cierraMin: 24 * 60, abreDomingo: true, siempre: true };
    }
    let cierra = null;
    for (const p of periodos) {
      const a = p.open;
      const c = p.close;
      if (!a || !c || a.day < 1 || a.day > 5) continue;
      let min = (c.hour ?? 0) * 60 + (c.minute ?? 0);
      if (c.day !== a.day) min += 24 * 60;
      cierra = cierra === null ? min : Math.max(cierra, min);
    }
    return { cierraMin: cierra, abreDomingo: periodos.some((p) => p.open && p.open.day === 0), siempre: false };
  };

  return lugares.map((l, i) => {
    const r = webs[i] ?? {};
    const html = !r.error && typeof r.html === 'string' ? r.html : '';
    const leida = html.length > 200;
    const textoWeb = leida ? corta(textoVisible(html), 2500) : '';
    const chat = leida ? (CHATS.find(([, re]) => re.test(html)) ?? [''])[0] : '';
    const agenda = AGENDA.test(l.web) || (leida && (AGENDA.test(html) || AGENDA.test(textoWeb)));
    const wa = (leida ? html.match(WA) : null) ?? (l.social ? l.web.match(WA) : null);
    const h = leeHorario(l.horario);
    const quejas = [];
    for (const rv of l.resenas) {
      if (rv.estrellas > 3) continue;
      const f = frases(rv.texto).find((x) => QUEJAS.some((re) => re.test(x)));
      if (f) quejas.push(corta(f, 160));
    }

    let preNota = 0;
    if (quejas.length) preNota += 3;
    if (quejas.length > 1) preNota += 2;
    if (leida && !chat) preNota += 2;
    else if (!l.web || l.social) preNota += 1;
    if (h.cierraMin !== null && h.cierraMin < 20 * 60) preNota += 1;
    if (h.abreDomingo === false) preNota += 1;
    if (l.total >= 40) preNota += 1;
    preNota = Math.min(10, preNota);

    const cierra = h.siempre ? '24 h' : h.cierraMin !== null ? hhmm(h.cierraMin) : '';
    const webEstado = !l.web ? 'no tiene' : l.social ? `solo redes sociales (${l.web})` : leida ? l.web : `${l.web} (no se pudo leer)`;
    const partes = [];
    if (h.siempre) partes.push('Abre 24 h');
    else if (cierra) partes.push(`Cierra ${cierra}`);
    if (!l.web) partes.push('Sin web');
    else if (l.social) partes.push('Solo redes, sin web propia');
    else if (!leida) partes.push('No se pudo leer su web');
    else partes.push(chat ? `Chat en la web (${chat})` : 'Sin chat en la web');
    if (agenda) partes.push('Agenda en línea');
    if (quejas.length) partes.push(`${quejas.length} ${quejas.length === 1 ? 'reseña dice' : 'reseñas dicen'} que no contestan`);
    if (l.rating) partes.push(`★${l.rating} (${l.total} reseñas)`);

    const horarioTexto = Array.isArray(l.horario?.weekdayDescriptions) ? l.horario.weekdayDescriptions.join(' · ') : '';
    const contexto = [
      `Negocio: ${l.nombre}`,
      `Dirección: ${l.direccion || 'sin dato'}`,
      `Calificación en Google: ${l.rating ? `${l.rating} (${l.total} reseñas)` : 'sin calificación'}`,
      `Horario: ${horarioTexto || 'sin dato'}`,
      `Web: ${webEstado}`,
      `Chat o bot en la web: ${leida ? chat || 'no se encontró' : 'no se sabe'}`,
      `Agenda en línea: ${agenda ? 'sí' : 'no se encontró'}`,
      `Botón de WhatsApp en la web: ${wa ? 'sí' : 'no se encontró'}`,
      `Reseñas (las más relevantes según Google, máximo 5):`,
      ...(l.resenas.length ? l.resenas.map((rv, k) => `${k + 1}. ${rv.estrellas}★${rv.hace ? ' · ' + rv.hace : ''}: "${rv.texto}"`) : ['(sin reseñas)']),
      `Texto de su web (inicio):`,
      textoWeb || '(no disponible)',
    ].join('\n');

    return {
      json: {
        placeId: l.placeId, nombre: l.nombre, direccion: l.direccion, telefono: l.telefono, whatsapp: wa ? wa[1] : '',
        web: l.web, maps: l.maps, rating: l.rating, total: l.total, horarioTexto, cierra, chat, agenda, webLeida: leida,
        quejas, resenas: l.resenas, textoWeb, preNota, senales: partes.join(' · '), contexto,
        nicho: String(cfg.nicho ?? '').trim() || 'dentista',
        ciudad: String(cfg.ciudad ?? '').trim(),
      },
    };
  });
};

// ---- Elige las mejores
const eligeLasMejores = ($, $input) => {
  const cfg = $('Tus datos').first().json;
  const base = $('Señales').all().map((i) => i.json);
  const ia = $input.all().map((i) => i.json);
  const cuantos = Math.max(1, Math.min(100, Math.round(Number(cfg.cuantos) || 20)));
  const corta = (s, n) => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, n);
  const plano = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[«»"“”'‘’]/g, '').replace(/\s+/g, ' ').trim();
  const fnv = (s, seed) => {
    let h = seed >>> 0;
    for (let k = 0; k < s.length; k++) {
      h ^= s.charCodeAt(k);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h.toString(36).padStart(7, '0').slice(-6);
  };
  const idDe = (placeId) => fnv(placeId, 2166136261) + fnv(placeId, 3735928559);
  const demoBase = String(cfg.demoUrl ?? '').trim();
  const demoDe = (id) => (demoBase ? `${demoBase}${demoBase.includes('?') ? '&' : '?'}c=${id}` : '');

  const filas = base.map((b, i) => {
    const r = ia[i] ?? {};
    const o = r.output && typeof r.output === 'object' ? r.output : {};
    const notaIA = Math.round(Number(o.nota));
    const valida = !r.error && Number.isFinite(notaIA) && notaIA >= 1 && notaIA <= 10;
    const cita = corta(o.evidencia, 300);
    const enResena = cita.length >= 12 && b.resenas.some((rv) => plano(rv.texto).includes(plano(cita)));
    const evidencia = enResena ? corta(cita, 160) : b.quejas[0] ?? '';
    const web = plano(b.textoWeb);
    const servicios = [];
    for (const s of Array.isArray(o.servicios) ? o.servicios : []) {
      const t = corta(s, 40);
      if (t.length >= 3 && web.includes(plano(t)) && !servicios.some((x) => plano(x) === plano(t))) servicios.push(t);
      if (servicios.length >= 8) break;
    }
    const id = idDe(b.placeId);
    return {
      id, nota: valida ? notaIA : b.preNota, notaDeIA: valida, preNota: b.preNota,
      motivo: corta(o.motivo, 140) || b.senales, evidencia, servicios: servicios.join(', '), demo: demoDe(id),
      nombre: b.nombre, direccion: b.direccion, telefono: b.telefono, whatsapp: b.whatsapp, web: b.web, maps: b.maps,
      total: b.total, horario: b.horarioTexto, cierra: b.cierra, chat: b.chat, webLeida: b.webLeida, senales: b.senales,
      nicho: b.nicho, ciudad: b.ciudad,
    };
  });
  filas.sort((a, b) => b.nota - a.nota || b.preNota - a.preNota || b.total - a.total || a.nombre.localeCompare(b.nombre));
  return filas.slice(0, cuantos).map((json) => ({ json }));
};

// ---- Revisa el mensaje
const revisaElMensaje = ($, $input) => {
  const cfg = $('Tus datos').first().json;
  const base = $('Elige las mejores').all().map((i) => i.json);
  const ia = $input.all().map((i) => i.json);
  const firma = String(cfg.tuNombre ?? '').trim();
  const limpia = (s) => String(s ?? '').replace(/\r/g, '').replace(/[ \t]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  const DINERO = /(US\$|\$|USD|MXN|COP|ARS|CLP|PEN|€)\s?\d|\d[\d.,]*\s?(USD|MXN|COP|ARS|CLP|PEN|€|d[oó]lares|pesos|euros)\b|\b\d+\s?%/i;
  return base.map((b, i) => {
    const r = ia[i] ?? {};
    const o = r.output && typeof r.output === 'object' ? r.output : {};
    let m = !r.error ? limpia(o.mensaje) : '';
    const partes = m.split(/((?<=[.!?…]|\{DEMO\})[ \t]+|[ \t]*\n+[ \t]*|[ \t]+(?=[¿¡]))/);
    let limpio = '';
    for (let k = 0; k < partes.length; k += 2) {
      if (!DINERO.test(partes[k]) && !/https?:\/\/|www\./i.test(partes[k])) limpio += partes[k] + (partes[k + 1] ?? '');
    }
    m = limpia(limpio);
    const deIA = m.length >= 40 && m.includes('{DEMO}');
    if (!deIA) {
      const observacion = b.evidencia
        ? `un paciente escribió en Google: «${b.evidencia.replace(/[\s.!…]+$/, '')}»`
        : b.cierra && b.cierra !== '24 h'
          ? `cierran a las ${b.cierra}${b.webLeida && !b.chat ? ' y en su web no hay chat' : ''}`
          : 'los mensajes que llegan fuera de horario se quedan sin respuesta hasta el día siguiente';
      m = [
        `Hola, equipo de ${b.nombre}. Vi que ${observacion}.`,
        `Les preparé una recepcionista con IA de prueba, con su nombre y su horario, para que la prueben esta noche como si fueran un paciente: {DEMO}`,
        `¿Me dicen qué les parece?`,
        firma,
      ].filter(Boolean).join('\n\n');
    }
    m = limpia(m.split('{DEMO}').join(b.demo || '[link de la demo]')).slice(0, 1000);
    const numero = String(b.whatsapp || b.telefono || '').replace(/\D/g, '');
    const abrir = numero.length >= 10 && numero.length <= 15 ? `https://wa.me/${numero}?text=${encodeURIComponent(m)}` : '';
    return { json: { ...b, mensaje: m, abrirWhatsApp: abrir, mensajeDeIA: deIA } };
  });
};

// ---- Busca en Google Maps (Places API real si hay key; si no, lugares.js)
const buscaEnMaps = (busquedas) => {
  const key = process.env.GOOGLE_MAPS_API_KEY;
  if (!key) {
    console.log('Sin GOOGLE_MAPS_API_KEY: uso lugares.js (negocios reales sacados de búsquedas web).');
    return require('./lugares.js');
  }
  const mask = 'places.id,places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri,places.rating,places.userRatingCount,places.regularOpeningHours,places.reviews,places.businessStatus,nextPageToken';
  const out = [];
  for (const { textQuery } of busquedas) {
    let pageToken;
    for (let k = 0; k < 3; k++) {
      const body = JSON.stringify({ textQuery, languageCode: tusDatos.idioma, regionCode: tusDatos.region, pageSize: 20, ...(pageToken ? { pageToken } : {}) });
      const res = JSON.parse(execFileSync('curl', ['-sS', '-X', 'POST', 'https://places.googleapis.com/v1/places:searchText', '-H', 'Content-Type: application/json', '-H', `X-Goog-Api-Key: ${key}`, '-H', `X-Goog-FieldMask: ${mask}`, '-d', body], { encoding: 'utf8' }));
      out.push(res);
      pageToken = res.nextPageToken;
      if (!pageToken) break;
    }
  }
  return out;
};

// ---- Lee su web
const leeSuWeb = (lugares) =>
  lugares.map((l) => {
    if (!l.webParaLeer) return { error: { message: 'URL vacía' } };
    try {
      const html = execFileSync('curl', ['-sSL', '-f', '-m', '10', '-A', 'Mozilla/5.0 (compatible; EncuentraClientes/1.0)', '-H', 'Accept-Language: es', l.webParaLeer], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
      return { html };
    } catch (e) {
      return { error: { message: String(e.stderr || e.message).trim().slice(0, 200) } };
    }
  });

// ================= Ejecución
salidas['Arma las búsquedas'] = corre(armaLasBusquedas, []);
console.log('Búsquedas:', salidas['Arma las búsquedas'].map((b) => b.textQuery));
salidas['Busca en Google Maps'] = buscaEnMaps(salidas['Arma las búsquedas']);
salidas['Junta las clínicas'] = corre(juntaLasClinicas, salidas['Busca en Google Maps']);
console.log('Negocios únicos:', salidas['Junta las clínicas'].length);
salidas['Lee su web'] = leeSuWeb(salidas['Junta las clínicas']);
console.log('Webs leídas:', salidas['Lee su web'].filter((w) => w.html && w.html.length > 200).length);
salidas['Señales'] = corre(senales, salidas['Lee su web']);
guarda('senales.json', salidas['Señales'].map((s) => ({ nombre: s.nombre, preNota: s.preNota, senales: s.senales, contexto: s.contexto })));

const calificacion = lee('calificacion.json');
if (!calificacion) { console.log('Listo senales.json. Falta calificacion.json (salida de "Califica con IA").'); process.exit(0); }
salidas['Califica con IA'] = calificacion;
salidas['Elige las mejores'] = corre(eligeLasMejores, calificacion);
guarda('elegidos.json', salidas['Elige las mejores'].map((e) => ({ id: e.id, nota: e.nota, nombre: e.nombre, motivo: e.motivo, senales: e.senales, evidencia: e.evidencia })));

const mensajes = lee('mensajes.json');
if (!mensajes) { console.log('Listo elegidos.json. Falta mensajes.json (salida de "Escribe el primer mensaje").'); process.exit(0); }
salidas['Revisa el mensaje'] = corre(revisaElMensaje, mensajes);

// ---- Guarda en Prospectos
const pad = (n) => String(n).padStart(2, '0');
const ahora = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Mexico_City' }));
const buscado = `${ahora.getFullYear()}-${pad(ahora.getMonth() + 1)}-${pad(ahora.getDate())} ${pad(ahora.getHours())}:${pad(ahora.getMinutes())}`;
const filas = salidas['Revisa el mensaje'].map((j) => ({
  ID: j.id, Nota: j.nota, 'Clínica': j.nombre, Motivo: j.motivo, Evidencia: j.evidencia, 'Señales': j.senales,
  'Teléfono': j.telefono, WhatsApp: j.whatsapp, Web: j.web, 'Google Maps': j.maps, 'Dirección': j.direccion,
  Horario: j.horario, Servicios: j.servicios, Nicho: j.nicho, Demo: j.demo, Mensaje: j.mensaje,
  'Abrir en WhatsApp': j.abrirWhatsApp, Buscado: buscado, Estado: '',
}));
guarda('prospectos.json', filas);
const cols = Object.keys(filas[0]);
const csv = [cols, ...filas.map((f) => cols.map((c) => f[c]))].map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
fs.writeFileSync(path.join(D, 'Prospectos.csv'), '﻿' + csv);
execFileSync('python3', [path.join(D, 'a_xlsx.py'), path.join(D, 'prospectos.json'), path.join(D, 'Prospectos.xlsx')], { stdio: 'inherit' });
console.log(`Hoja Prospectos: ${filas.length} filas -> Prospectos.xlsx / Prospectos.csv`);
