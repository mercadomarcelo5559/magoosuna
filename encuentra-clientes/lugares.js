// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-12: Juriquilla, Centro Sur y El Refugio (Querétaro).
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
    textQuery: 'dentista en Juriquilla, Querétaro, Querétaro',
    places: [
      lugar('dentalia-juriquilla', 'dentalia Juriquilla', 'Residencial Caletto, 2º piso, Juriquilla, Querétaro, Qro.', '+52 442 688 1100', 'https://www.dentalia.com/clinica/dentalia-juriquilla', { h: { ...LV([9, 20]), 6: [9, 18], 0: [10, 17] } }),
      lugar('la-clinica-dental-qro-juriquilla', 'La Clínica Dental Querétaro (Juriquilla)', 'Juriquilla, Querétaro, Qro.', '+52 442 456 0193', 'https://dentalqueretaro.com/', { h: { ...LV([9, 19]), 6: [10, 14] } }),
      lugar('dental-arch-clinic', 'Dental Arch Clinic', 'Plaza Juriquilla, junto al Restaurante Emilio\'s, Juriquilla, Querétaro, Qro.', '+52 442 379 7079', 'https://dentalarchclinic.com/'),
      lugar('clinica-dental-juriquilla', 'Clínica Dental Juriquilla', 'Corporativo Omega #512, oficina 102, Juriquilla, Querétaro, Qro.', '+52 442 234 1404', 'https://www.clinicadentaljuriquilla.com/'),
      lugar('centro-dental-qro-arias', 'Centro Dental Querétaro · Dr. Jorge Arias', 'Av. de las Ciencias 2058, piso 31, consultorio 3104, Juriquilla, 76226 Querétaro, Qro.', '', 'https://www.dentistasenqro.mx/'),
      lugar('dental-center-juriquilla', 'Dental Center Juriquilla', 'Juriquilla, Querétaro, Qro.', '+52 442 688 5562', ''),
      lugar('neident', 'Neident', 'Juriquilla, Querétaro, Qro.', '+52 442 234 2105', ''),
    ],
  },
  {
    textQuery: 'dentista en Centro Sur, Querétaro, Querétaro',
    places: [
      lugar('clinica-dental-centro-sur', 'Clínica Dental Centro Sur', 'Av. Fray Luis de León 7072, consultorio 410 (Momentum Centro Sur), Querétaro, Qro.', '+52 442 142 9871', 'https://clinicadentalcentrosur.com/', { h: { 1: [9.5, 20], 2: [9.5, 20], 3: [9.5, 20], 4: [9, 14.5], 6: [9.5, 20], 0: [9.5, 20] } }),
      lugar('clinica-dental-especializada-qro', 'Clínica Dental Especializada', 'Av. Manuel Gómez Morín 3970, int. 101, Centro Sur, Querétaro, Qro.', '+52 442 295 5761', 'http://clinicadentalespecializada.com/', { h: LV([[10, 14], [16, 20]]) }),
      lugar('dentnuvo', 'DentNuvó · Dra. Maripaz Aguilar', 'Av. Colinas del Cimatario 401, consultorio 303, Querétaro, Qro.', '+52 442 609 8988', ''),
      lugar('dental-center-sur', 'Dental Center Sur', 'Cerro Escondido 101, Querétaro, Qro.', '+52 442 365 7455', 'https://www.facebook.com/p/Dental-Center-Sur-100084280477713/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
      lugar('denti-smiles-centro-sur', 'Denti Smiles Centro Sur', 'Blvd. Centro Sur 40, La Alhambra, Querétaro, Qro.', '+52 442 716 1274', ''),
    ],
  },
  {
    textQuery: 'dentista en El Refugio, Querétaro, Querétaro',
    places: [
      lugar('smile-solution-qro', 'Smile Solution Querétaro', 'Anillo Vial Fray Junípero Serra 9390, local 21, El Refugio, Querétaro, Qro.', '+52 442 379 3134', ''),
      lugar('dental-360-refugio', 'Dental 360°', 'Calle Campo Real 1606, El Refugio, Querétaro, Qro.', '+52 442 471 4066', '', { h: { ...LV([8, 20]), 6: [8, 14] } }),
      lugar('happy-dental-house', 'Happy Dental House', 'Campo Real 1419, El Refugio, Querétaro, Qro.', '+52 442 779 1239', 'https://happydentalhouse.com/', { h: { ...LV([10, 20]), 6: [10, 15] } }),
    ],
  },
];
