// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-21: Boca del Río (Veracruz), Centro (Oaxaca) y Centro (Saltillo).
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
    textQuery: 'dentista en Boca del Río, Veracruz',
    places: [
      lugar('micdent', 'Micdent Mi Clínica Dental', 'Av. Salvador Díaz Mirón 332-B, Jardines de Virginia, 94294 Boca del Río, Ver.', '+52 229 929 6440', '', { h: { ...LV([8, 20]), 6: [8, 20], 0: [10, 14] } }),
      lugar('endodentist', 'Clínica EndoDentist', 'Av. Reyes Heroles 64, Costa Verde, 94294 Boca del Río, Ver.', '+52 229 241 7380', ''),
      lugar('divdent', 'DivDent', 'Av. de las Américas 590, Boca del Río, Ver.', '+52 229 101 6401', ''),
      lugar('iora-dental', 'Iora Clínica Dental de Implantología', 'Calle Vasco de Balboa 191, Virginia, Boca del Río, Ver.', '+52 229 985 2658', 'https://www.clinicadentaliora.com/', { h: { ...LV([[9, 14], [16, 20]]), 6: [10, 14] } }),
      lugar('bocadent', 'BocaDent', 'Calle Texcoco 341, Col. Rigo, Boca del Río, Ver.', '+52 229 922 1748', 'http://www.bocadent.com.mx/index-4.html', { h: { 2: [10, 20], 3: [10, 14], 4: [10, 20], 5: [10, 20], 6: [10, 14] } }),
      lugar('arte-dental-kids', 'Arte Dental Kids', 'Calle Pista 256, local 5, Hípico, Boca del Río, Ver.', '+52 229 980 3231', 'https://www.artedentalkids.com/', { h: { ...LV([[9, 14], [16, 20]]), 6: [9, 14] } }),
      lugar('montdent-veracruz', 'MontDent Veracruz', 'Plaza Vela, piso 3, int. 303, Boca del Río, Ver.', '+52 229 223 2538', '', { h: { ...LV([10, 20]), 6: [10, 20], 0: [9, 16] } }),
    ],
  },
  {
    textQuery: 'dentista en Centro, Oaxaca de Juárez, Oaxaca',
    places: [
      lugar('odontoax', 'ODONTOAX', 'Félix Romero #100 esq. Gerardo Varela, Col. La Cascada, Oaxaca de Juárez, Oax.', '+52 951 518 5610', 'https://odontoax.getnetstore.mx/', { h: { ...LV([9, 19]), 6: [9, 15] } }),
      lugar('encisan', 'Encisan · Encías e Implantes', 'Matamoros 204, Centro, Oaxaca de Juárez, Oax.', '+52 951 514 1928', 'https://www.encisan.com/', { h: { ...LV([10, 18]), 6: [10, 14] } }),
      lugar('crisal-dent', 'Crisal Dent', 'Gregorio Torres Quintero 405C, 68016 Oaxaca de Juárez, Oax.', '+52 951 285 5271', 'https://crisaldent.ueniweb.com/'),
      lugar('oaxaca-dental', 'Oaxaca Dental', 'Carlos María Bustamante 312-A, Centro, Oaxaca de Juárez, Oax.', '+52 951 516 4959', '', { h: LV([9, 17]) }),
    ],
  },
  {
    textQuery: 'dentista en Centro, Saltillo, Coahuila',
    places: [
      lugar('icodent-saltillo', 'Icodent Consultorio Dental', 'Ignacio Allende 617, Zona Centro, 25000 Saltillo, Coah.', '+52 844 528 7536', '', { h: { ...LV([10, 19]), 6: [10, 17] } }),
      lugar('odonic', 'Clínica Dental Odonic', 'Álvaro Obregón 211, Zona Centro, Saltillo, Coah.', '+52 844 410 4766', '', { h: { ...LV([10, 19]), 6: [10, 15] } }),
      lugar('dental-art-saltillo', 'Dental-art Clínica Dental', 'Urdiñola Sur 554-A, Zona Centro, Saltillo, Coah.', '+52 844 297 0184', '', { h: { ...LV([10, 19]), 6: [10, 14] } }),
      lugar('clinica-rio-centro-saltillo', 'Clínica Río Sucursal Centro', 'C. Xicoténcatl 520, Zona Centro, Saltillo, Coah.', '+52 844 143 6913', '', { h: { ...LV([15, 20]), 6: [9, 15] } }),
      lugar('dental-acuna', 'Dental Acuña', 'C. Manuel Acuña 404-490, Zona Centro, Saltillo, Coah.', '+52 844 344 8422', '', { h: { ...LV([9.5, 19.5]), 6: [9.5, 17] } }),
      lugar('dental-center-saltillo', 'Dental Center Saltillo', 'Col. Latinoamericana 2da Ampliación, Saltillo, Coah.', '+52 844 293 5990', 'https://www.dentalcentersaltillo.com/', { h: { ...LV([[9.5, 13], [15, 19]]), 6: [9.5, 13] } }),
      lugar('dr-becerril', 'Dr. Becerril · Clínica Dental Especializada', 'Luis Echeverría 715, Col. Latinoamericana, Saltillo, Coah.', '+52 844 488 1588', 'https://www.drbecerril.com/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
    ],
  },
];
