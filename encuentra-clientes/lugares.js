// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-16: Campestre, Centro y Jardines del Moral (León, Guanajuato).
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
    textQuery: 'dentista en Campestre, León, Guanajuato',
    places: [
      lugar('dra-fatima-herrera', 'Dra. Fátima Herrera · Cirujana Maxilofacial', 'Campestre 3004, int. 9, Cañada del Refugio, León, Gto.', '+52 477 850 3000', ''),
      lugar('sonrident-leon', 'Clínica Sonrident', 'Hacienda de los Cárcamos 108, Hacienda del Campestre, 37125 León, Gto.', '', 'https://clinicasonrident.com/', { h: { ...LV([[10, 14], [16, 20]]), 6: [10, 14] } }),
      lugar('qualitydent-leon', 'Clínica Dental QualityDent', 'Valle de Bravo 201, Valle del Campestre, León, Gto.', '+52 477 717 2046', ''),
      lugar('odontologia-campestre-lasalle', 'Clínica de Odontología Campestre (De La Salle)', 'Av. Universidad 602, Lomas del Campestre, León, Gto.', '+52 477 710 8500', ''),
      lugar('dental-excellence-leon', 'Dental Excellence', 'Calle Plateros 107, Valle del Campestre, León, Gto.', '+52 477 774 0824', '', { h: { ...LV([9, 20]), 6: [9, 14] } }),
      lugar('kenji-sashida', 'Kenji Sashida Clínica Dental', 'Manantial 802, Lomas del Campestre, León, Gto.', '+52 477 395 9161', '', { h: { ...LV([9, 17]), 6: [9, 17] } }),
    ],
  },
  {
    textQuery: 'dentista en Centro, León, Guanajuato',
    places: [
      lugar('clinica-dental-hr', 'Clínica Dental HR', '5 de Febrero 724, consultorio 112, Centro, 37000 León, Gto.', '+52 477 107 3224', '', { h: { ...LV([9, 21]), 6: [9, 14] } }),
      lugar('consultorio-dental-del-centro-leon', 'Consultorio Dental Del Centro', 'Av. Miguel Alemán 203, Obrera, 37340 León, Gto.', '+52 477 364 8320', ''),
      lugar('clinica-dental-miguel-aleman', 'Clínica Dental Miguel Alemán', 'Av. Miguel Alemán 503, Centro, 37000 León, Gto.', '+52 477 154 8733', ''),
      lugar('mcdental-leon', 'McDental León', 'Mariano Escobedo 1501, local 7, Col. Andrade, 37370 León, Gto.', '+52 477 429 7423', 'https://cita.mcdental.com.mx/sucursal/leon', { h: { ...LV([9, 20]), 6: [9, 20] } }),
    ],
  },
  {
    textQuery: 'dentista en Jardines del Moral, León, Guanajuato',
    places: [
      lugar('la-clinica-dental-leon', 'La Clínica Dental León', 'Calle Cañada 405, Jardines del Moral, León, Gto.', '+52 477 454 0411', 'https://laclinicaleon.dental/', { h: { ...LV([9, 20]), 6: [9, 20] } }),
      lugar('dentistry-leon', 'Dentistry León Clínica Dental', 'Farallón 364, Jardines del Moral, 37160 León, Gto.', '+52 477 767 1913', '', { h: { ...LV([8, 20]), 6: [8, 20] } }),
      lugar('dental-romo', 'Clínica Dental Romo', 'Av. Guanajuato 1302, Jardines del Moral, 37160 León, Gto.', '+52 477 717 5982', 'https://www.dentalromo.mx/contacto/'),
      lugar('ortofacial-center', 'Ortofacial Center', 'Agua Azul 702, Jardines del Moral, 37160 León, Gto.', '+52 477 497 4929', 'https://www.ortofacialcenter.com/', { h: { ...LV([[9, 14], [16, 20]]), 6: [9, 14] } }),
      lugar('bajio-dental-esthetics', 'Bajío Dental Esthetics', 'Paseo del Moral 415, Jardines del Moral, León, Gto.', '+52 477 407 2619', 'https://www.bajiodentalesthetics.com/', { h: { ...LV([[10, 14], [16, 20]]), 6: [9, 14] } }),
      lugar('oh-dental-leon', 'Oh! Dental León', 'León 109, Jardines del Moral, 37160 León, Gto.', '+52 477 170 7874', '', { h: { ...LV([9, 19.5]), 6: [9, 14] } }),
    ],
  },
];
