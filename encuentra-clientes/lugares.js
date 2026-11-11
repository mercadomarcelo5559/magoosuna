// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-11: Angelópolis, La Paz y Centro (Puebla).
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
    textQuery: 'dentista en Angelópolis, Puebla, Puebla',
    places: [
      lugar('dental-angelopolis', 'Dental Angelópolis', '33 Sur 2310, consultorios 203 y 204, Santa Cruz Los Ángeles, 72400 Puebla, Pue.', '+52 222 249 4940', 'https://www.dentalangelopolis.com/', { h: { ...LV([[10.5, 14], [16.5, 19.5]]), 6: [10.5, 14] } }),
      lugar('clinica-dental-77', 'Clínica Dental 77', 'Torres Médicas Angelópolis, Torre 2, piso 20, consultorio 2004, 72820 San Andrés Cholula, Pue.', '+52 221 187 5666', 'https://clinicadental77.com/', { h: { ...LV([9, 20]), 6: [9, 16] } }),
      lugar('endodoncia-puebla', 'Endodoncia Puebla · Dr. José Antonio Con', 'Torres Médicas Angelópolis, Torre 1, piso 11, consultorio 1129, 72820 Puebla, Pue.', '+52 221 346 9691', 'https://www.endodonciapuebla.mx/', { h: LV([10, 19]) }),
    ],
  },
  {
    textQuery: 'dentista en La Paz, Puebla, Puebla',
    places: [
      lugar('consultorio-23-sur', 'Consultorio Dental 23 Sur', 'Calle 23 Sur, La Paz, Puebla, Pue.', '+52 222 231 9204', ''),
      lugar('montdent-la-paz', 'Clínica Dental Montdent La Paz', 'C. Tlaxco 136, La Paz, Puebla, Pue.', '+52 222 273 2950', '', { h: { ...LV([15, 20]), 6: [15, 20], 0: [9, 16] } }),
    ],
  },
  {
    textQuery: 'dentista en Centro, Puebla, Puebla',
    places: [
      lugar('dentista-puebla-10-ote', 'Dentista Puebla', 'Av. 10 Ote. 216, Centro histórico, Puebla, Pue.', '+52 222 703 2561', ''),
      lugar('clinica-dental-moderna-puebla', 'Clínica Dental Moderna', 'Av. 8 Pte. 120, Centro histórico, Puebla, Pue.', '+52 222 242 0844', ''),
      lugar('cirujano-dentistas-5-nte', 'Cirujano Dentistas', 'Calle 5 Nte. 1208, alto 3, Centro histórico, Puebla, Pue.', '+52 222 246 6003', ''),
      lugar('maxilofacial-implantes-puebla', 'Maxilofacial Implantes Puebla · Dr. Juan Peña Lares', 'Av. 5 Pte. 715, Centro histórico, Puebla, Pue.', '+52 222 325 5305', ''),
      lugar('dra-ernestina-gasca', 'Dra. Ernestina Gasca', '5 de Mayo 1003, Centro histórico, Puebla, Pue.', '+52 222 128 2452', ''),
    ],
  },
];
