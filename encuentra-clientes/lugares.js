// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-13: García Ginerés, Altabrisa y Montebello (Mérida, Yucatán).
// Una respuesta por zona, igual que "Arma las búsquedas" -> "Busca en Google Maps".
// Calificaciones: de agregadores (no de Google). Reseñas: no se obtuvieron textos, se dejan vacías (no se inventan).
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
// h: { 1: [9, 19], ..., 6: [10, 14] }  (0 = domingo)
const hm = (x) => ({ hour: Math.floor(x), minute: Math.round((x % 1) * 60) });
const txt = (x) => `${Math.floor(x)}:${String(Math.round((x % 1) * 60)).padStart(2, '0')}`;
const rangos = (v) => (Array.isArray(v[0]) ? v : [v]);
const horario = (h) => {
  if (!h) return undefined;
  const periods = Object.entries(h).flatMap(([d, v]) => rangos(v).map(([a, c]) => ({ open: { day: +d, ...hm(a) }, close: { day: +d, ...hm(c) } })));
  const orden = [1, 2, 3, 4, 5, 6, 0];
  const weekdayDescriptions = orden.map((d) => `${DIAS[d]}: ${h[d] ? rangos(h[d]).map(([a, c]) => `${txt(a)}–${txt(c)}`).join(', ') : 'Cerrado'}`);
  return { periods, weekdayDescriptions };
};
const semana = (a, c, sab, dom) => {
  const h = { 1: [a, c], 2: [a, c], 3: [a, c], 4: [a, c], 5: [a, c] };
  if (sab) h[6] = sab;
  if (dom) h[0] = dom;
  return h;
};
const maps = (n, d) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${n}, ${d}`)}`;
const lugar = (id, nombre, direccion, tel, web, extra = {}) => ({
  id: `web-${id}`,
  displayName: { text: nombre },
  formattedAddress: direccion,
  internationalPhoneNumber: tel || undefined,
  websiteUri: web || undefined,
  googleMapsUri: maps(nombre, direccion),
  rating: extra.rating,
  userRatingCount: extra.total,
  regularOpeningHours: horario(extra.h),
  reviews: [],
  businessStatus: 'OPERATIONAL',
});

const LV = (r) => ({ 1: r, 2: r, 3: r, 4: r, 5: r });
module.exports = [
  {
    textQuery: 'dentista en García Ginerés, Mérida, Yucatán',
    places: [
      lugar('smile-center-merida', 'Smile Center Mérida', 'Calle 7 #215a, int. 206, x 32 y 34, García Ginerés, Mérida, Yuc.', '+52 999 943 9183', 'https://smilecentermerida.com/', { h: { ...LV([[9, 13.5], [16.5, 20]]), 6: [9, 14] } }),
      lugar('centro-estetico-odontologico', 'Centro Estético Odontológico', 'Av. Cupules 74 x 6 y 8, García Ginerés, Mérida, Yuc.', '+52 999 920 2461', ''),
      lugar('espacio-dental-merida', 'Espacio Dental', 'Calle 20 #210, García Ginerés, Mérida, Yuc.', '+52 999 920 8683', '', { h: { ...LV([[9, 13], [16, 20]]), 6: [[9, 13], [16, 20]] } }),
      lugar('dental-int', 'Dental Int', 'Calle 9 #210, García Ginerés, 97070 Mérida, Yuc.', '+52 999 532 7977', ''),
      lugar('unidad-medica-garcia-gineres', 'Unidad Médica García Ginerés (Dentista Especialista)', 'Calle 27 #190, García Ginerés, Mérida, Yuc.', '+52 999 925 9614', ''),
    ],
  },
  {
    textQuery: 'dentista en Altabrisa, Mérida, Yucatán',
    places: [
      lugar('dentalia-altabrisa', 'dentalia Altabrisa', 'Fraccionamiento Altabrisa, 97133 Mérida, Yuc.', '+52 999 167 9475', 'https://www.dentalia.com/'),
      lugar('quality-dental', 'Quality Dental', 'C. 26 212 x 7, Altabrisa Med Plaza, Mérida, Yuc.', '+52 999 233 5331', 'http://dentistayucatan.com/', { h: { 1: [9, 19], 2: [9, 19], 3: [9, 19], 4: [9, 19], 5: [9, 15], 6: [9, 13] } }),
      lugar('confidence-dental-group', 'Confidence Dental Group', 'Plaza Puerta de Hierro, C. 15 521, local 14, Altabrisa, 97130 Mérida, Yuc.', '+52 999 429 1747', ''),
    ],
  },
  {
    textQuery: 'dentista en Montebello, Mérida, Yucatán',
    places: [
      lugar('grupo-dental-bosques', 'Grupo Dental Bosques', 'Calle 36 Diagonal 306 x 28, Montebello, 97113 Mérida, Yuc.', '+52 999 913 9427', 'https://gdb.com.mx/'),
      lugar('biopediatrics', 'Biopediatrics', 'Calle 16 No. 481 x 33, Montebello, Mérida, Yuc.', '+52 999 847 1072', 'https://www.biopediatricsdentistry.com/es/odontopediatra-meridayucatan-1', { h: { ...LV([9, 20]), 6: [9, 14] } }),
      lugar('ident-design', 'iDent Design Plaza Luxury', 'Montebello, Mérida, Yuc.', '+52 999 922 8391', ''),
    ],
  },
];
