// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-26: Valle Oriente (San Pedro), Contry (Monterrey) y Guadalupe Centro (NL).
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
    textQuery: 'dentista en Valle Oriente, San Pedro Garza García, Nuevo León',
    places: [
      lugar('zurit-dental', 'Zurit Dental Studio', 'Río Guadalquivir 112 Ote., Col. Del Valle, San Pedro Garza García, N.L.', '+52 81 2611 7832', 'https://www.zurit.com.mx/dentistas-en-san-pedro/'),
      lugar('marfil-dental-studio', 'Marfil Dental Studio', 'Moll del Valle, 4º piso, studio 410, San Pedro Garza García, N.L.', '+52 81 2362 0223', 'https://www.marfildentalstudio.com/nosotros.html'),
    ],
  },
  {
    textQuery: 'dentista en Contry, Monterrey, Nuevo León',
    places: [
      lugar('dentagrama', 'Dentagrama', 'Av. Alfonso Reyes 269, Contry, Monterrey, N.L.', '+52 81 1727 2481', 'https://www.doctoralia.com.mx/clinicas/dentagrama'),
      lugar('dentastic', 'Dentistas Dentastic', 'Alfonso Reyes 351, Contry Tesoro, Monterrey, N.L.', '+52 81 2235 9867', 'https://www.dentistasdentastic.com/', { h: { ...LV([9, 19]), 6: [10, 14] } }),
      lugar('cantu-martinez', 'Cantú & Martínez Odontología Integral', 'Revolución 3540, Contry Tesoro, 64850 Monterrey, N.L.', '+52 81 1967 1112', '', { h: { ...LV([[9.5, 13], [15, 19]]), 6: [9.5, 13] } }),
      lugar('maas-dentistas', 'MAAS Dentistas', 'Av. Constelaciones 111, Contry, Monterrey, N.L.', '+52 81 1360 3501', 'https://en.maasdentistas.com/', { h: { ...LV([10, 20]), 6: [10, 16] } }),
      lugar('energia-dental', 'Energía Dental', 'Av. Revolución 710-B, Contry, Monterrey, N.L.', '+52 81 1878 2814', ''),
      lugar('consultorio-constelaciones-180', 'Consultorio Dental Constelaciones 180', 'Calle Constelaciones 180 A, Contry, Monterrey, N.L.', '+52 81 8357 8412', ''),
    ],
  },
  {
    textQuery: 'dentista en Guadalupe Centro, Guadalupe, Nuevo León',
    places: [
      lugar('dental-vidana', 'Clínica Dental Vidaña', 'Carretera a Reynosa 2208, Hacienda La Trinidad, 67190 Guadalupe, N.L.', '+52 81 4273 9257', '', { h: { ...LV([9, 19]), 6: [9, 16] } }),
      lugar('smilen', 'Smilēn Clínica Dental', 'Av. Paseo de las Américas 2101, local 17b, 2º piso, Contry Sol, 67174 Guadalupe, N.L.', '+52 81 1306 7952', '', { h: { ...LV([9, 19]), 6: [9, 14] } }),
      lugar('dental-sosa', 'Clínica Dental Sosa (Dentaldav)', 'C. Guadalupe 700-53, Centro de Guadalupe, 67140 Guadalupe, N.L.', '+52 81 8117 4435', '', { h: { ...LV([10.5, 18.5]), 6: [10.5, 16] } }),
      lugar('dent-monterrey', 'Dent Monterrey', 'C. Guadalupe 632, Centro de Guadalupe, 67100 Guadalupe, N.L.', '+52 81 1093 2253', '', { h: { ...LV([[9, 13], [15, 19]]), 6: [9, 14] } }),
      lugar('odontologia-integral-infantil-gpe', 'Odontología Integral e Infantil', 'Av. Santa Rosa de Lima 1495, Santa María, 67198 Guadalupe, N.L.', '+52 81 8361 4806', '', { h: { ...LV([10, 20]), 6: [12, 17] } }),
      lugar('odontosmile-gpe', 'Odontosmile', 'Plaza Mirador 2500, local 43, Mirador de la Silla, 67170 Guadalupe, N.L.', '+52 81 3483 3419', '', { h: { ...LV([10, 20]), 6: [10, 20] } }),
      lugar('dentistas-linda-vista', 'Los Dentistas Linda Vista', 'Linda Vista, Guadalupe, N.L.', '+52 81 1245 1026', ''),
    ],
  },
];
