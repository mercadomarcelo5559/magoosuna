// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-14: Zona Río, Otay y Playas de Tijuana (Tijuana, BC).
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
    textQuery: 'dentista en Zona Río, Tijuana, Baja California',
    places: [
      lugar('vides-dental', 'Vides Dental Group', 'Leona Vicario 1451, int. 207, Zona Urbana Río, Tijuana, B.C.', '+52 663 237 7777', 'https://videsdentalgroup.com/', { h: { ...LV([9, 17]), 6: [9, 14] } }),
      lugar('dental-rio-tijuana', 'Dental Río', 'Leona Vicario 1450, int. 204-A, Zona Río, Tijuana, B.C.', '+52 664 321 3663', 'https://dentalriotijuana.com/', { h: { ...LV([8, 17]), 6: [8, 17], 0: [8, 17] } }),
      lugar('dental-hc-tijuana', 'Dental H&C Tijuana', 'Paseo de los Héroes C 27-A, Plaza Río, Tijuana, B.C.', '+52 664 634 6307', 'https://www.dentalhctijuana.com/', { h: { ...LV([10, 18.5]), 6: [9, 16], 0: [10, 13] } }),
      lugar('advanced-smiles', 'Advanced Smiles Dentistry', 'Calle Germán Gedovius 10489, local 102, Zona Río, Tijuana, B.C.', '+52 664 634 3978', 'https://advancedsmilesdentistry.com/', { h: { ...LV([9, 18]), 6: [9, 14] } }),
      lugar('dentiland', 'Dentiland', 'Ignacio Comonfort 9350, Zona Urbana Río, Tijuana, B.C.', '+52 664 684 7285', 'https://www.dentiland.net/', { h: { ...LV([9, 18]), 6: [9, 14] } }),
      lugar('clinica-dental-coronel', 'Clínica Dental Coronel', 'Fray Servando Teresa de Mier 1351, int. 101, Zona Río, Tijuana, B.C.', '+52 664 905 9388', 'https://clinicadentalcoronel.com/', { h: { ...LV([10, 18]), 6: [9, 16] } }),
      lugar('dental-ramos', 'Dental Ramos Clínica', 'Blvd. Sánchez Taboada 10110, Plaza Financiera, Zona Río, Tijuana, B.C.', '+52 663 436 7008', 'https://dentalramosclinic.com/contact-us/', { h: { ...LV([10, 18]), 6: [10, 18] } }),
    ],
  },
  {
    textQuery: 'dentista en Otay, Tijuana, Baja California',
    places: [
      lugar('otay-dental-center', 'Otay Dental Center', 'Carretera Aeropuerto 1900, local E-21, C.C. Otay Constituyentes, Tijuana, B.C.', '+52 663 206 4209', 'https://otaydentalcenter.com/', { h: { ...LV([9, 17]), 6: [9, 15] } }),
      lugar('dentistas-tijuana-otay', 'Dentistas Tijuana', 'Av. Gral. Venustiano Carranza 19555, Otay Galerías, 22436 Tijuana, B.C.', '+52 664 624 6080', 'https://www.dentistastijuana.com/contact', { h: { ...LV([10, 18]), 6: [10, 14] } }),
      lugar('otay-dental-care', 'Otay Dental Care', 'Plaza Centenario, Blvd. de las Bellas Artes 17638, local 10, Garita de Otay, Tijuana, B.C.', '+52 664 647 5258', ''),
      lugar('dental-vancouver-otay', 'Dental Vancouver Otay', 'Blvd. Industrial 1715, local A-3, Plaza Amistad, Otay Constituyentes, Tijuana, B.C.', '+52 664 904 1233', 'https://www.facebook.com/dentalvancouverotay/'),
      lugar('dental-clinic-otay', 'Dental Clinic Otay', 'Otay, Tijuana, B.C.', '+52 664 193 2917', 'https://www.facebook.com/Dentalclinicotay7175/'),
      lugar('otay-dental-group', 'Otay Dental Group', 'Aeropuerto 16000, local 614, La Pechuga, Tijuana, B.C.', '+52 664 647 5013', '', { h: { ...LV([10, 18]), 6: [10, 18] } }),
    ],
  },
  {
    textQuery: 'dentista en Playas de Tijuana, Tijuana, Baja California',
    places: [
      lugar('muela-dental', 'Muela Dental', 'Paseo Pedregal 2308, Secc. El Dorado, Playas de Tijuana, B.C.', '+52 664 688 3455', '', { h: { ...LV([9, 16]), 6: [8, 15] } }),
      lugar('dental-image-playas', 'Dental Image Specialty Center Playas', 'P.º del Pedregal 460, int. 4, Las Flores, Playas de Tijuana, B.C.', '+52 664 976 5911', 'https://dentalimage.com/other-pages', { h: { ...LV([10.5, 19.5]), 6: [9, 15] } }),
      lugar('dental-sparks-playas', 'Dental Sparks Playas', 'Paseo Ensenada 1249-C, Secc. Jardines del Sol, Playas de Tijuana, B.C.', '+52 664 280 2921', 'https://www.facebook.com/dentalsparksplayas/'),
      lugar('international-dental-center', 'International Dental Center', 'De La Lluvia 2720, Costa Hermosa, Playas de Tijuana, B.C.', '+52 664 630 1345', ''),
      lugar('clinica-dental-perlita', 'Clínica Dental Perlita', 'Del Rocío 671, Jardines Playas de Tijuana, B.C.', '+52 664 631 1298', ''),
      lugar('dental-care-playas', 'Dental Care Playas', 'Paseo Playas de Tijuana 1020, Playas de Tijuana, B.C.', '+52 664 631 8480', ''),
    ],
  },
];
