// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-22: Centro (Torreón), Tabasco 2000 (Villahermosa) y Zona Dorada (Mazatlán).
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
    textQuery: 'dentista en Centro, Torreón, Coahuila',
    places: [
      lugar('laguna-dent', 'Laguna Dent', 'Blvd. Revolución 585 Ote., Centro, 27000 Torreón, Coah.', '+52 871 711 2207', 'https://www.lagunadent.com/', { h: { ...LV([10, 19]), 6: [10, 15] } }),
      lugar('sereya-dentales', 'Sereya Dentales', 'Calzada Cuauhtémoc 270 Sur, Centro, Torreón, Coah.', '+52 871 405 1474', 'https://sereyadentales.com/', { h: { ...LV([9, 19]), 6: [10, 14] } }),
      lugar('aoral-clinic', 'Aoral Clinic', 'Blvd. Independencia 144, Centro, Torreón, Coah.', '+52 871 718 4832', 'https://www.aoralclinic.com/', { h: { ...LV([9, 18]), 6: [9, 14] } }),
      lugar('dental-center-juarez-trc', 'Dental Center Juárez', 'Av. Juárez 2767, Centro, Torreón, Coah.', '+52 871 727 6525', '', { h: { ...LV([16, 19]), 6: [10.5, 17], 0: [10, 13] } }),
      lugar('dent-clinica-dental-trc', 'Dent Clínica Dental', 'Av. Hidalgo 3125 Ote., Nuevo Torreón, Torreón, Coah.', '+52 871 296 3651', 'https://clinicadent.com/', { h: { ...LV([9, 19]), 6: [9, 13] } }),
      lugar('dazujo-torreon', 'Dazujo Clínica Dental', 'Blvd. La Libertad 750, Torreón, Coah.', '+52 871 222 2162', ''),
      lugar('dental-21-torreon', 'Dental 21', 'Matamoros 1578 Pte., Torreón, Coah.', '+52 871 463 0606', ''),
    ],
  },
  {
    textQuery: 'dentista en Tabasco 2000, Villahermosa, Tabasco',
    places: [
      lugar('orthocity', 'Orthocity Clínica Dental Especializada', 'Av. Paseo Tabasco 1404-1, Tabasco 2000, 86035 Villahermosa, Tab.', '+52 993 316 9113', 'https://www.orthocityvhsa.com/', { h: { ...LV([10, 20]), 6: [10, 14] } }),
      lugar('biodentis', 'Biodentis', 'Prol. 27 de Febrero 3103, Fracc. Galaxias, Tabasco 2000, Villahermosa, Tab.', '+52 993 315 6277', 'http://www.biodentis.com.mx/'),
      lugar('smile-cuidado-dental-familiar', 'Smile Cuidado Dental Familiar', 'Blvd. Adolfo Ruiz Cortines 1310, Plaza Olmeca, Tabasco 2000, Villahermosa, Tab.', '+52 993 291 6046', '', { h: { ...LV([14, 20]), 6: [9.5, 20] } }),
      lugar('clinica-dental-villahermosa', 'Clínica Dental Villahermosa', 'Ernesto Malda 206, Centro, Villahermosa, Tab.', '+52 993 278 8631', '', { h: { ...LV([8.5, 20]), 6: [8.5, 20] } }),
      lugar('odonto-vitalis', 'Odonto Vitalis', 'Calle Sindicato del Trabajo 120 C, Adolfo López Mateos, Villahermosa, Tab.', '+52 993 131 0886', 'https://www.odontovitalis.com/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
    ],
  },
  {
    textQuery: 'dentista en Zona Dorada, Mazatlán, Sinaloa',
    places: [
      lugar('gavito-dental-care', 'Dr. Francisco Gavito · Dental Care Center', 'Camarón Sábalo 51, local 10, Zona Dorada, 82110 Mazatlán, Sin.', '+52 669 984 5823', ''),
      lugar('coppel-dental', 'Clínica Dental Dr. Roberto Coppel', 'Av. Camarón Sábalo 1502, 2do piso, Las Gaviotas, Zona Dorada, 82110 Mazatlán, Sin.', '+52 669 913 4111', ''),
      lugar('clinica-dental-especialidades-mzt', 'Clínica Dental Especialidades', 'Tacuba 305-A, Playas del Sol, Mazatlán, Sin.', '+52 669 261 1711', 'https://clinicadentalespecialidades.com/', { h: { ...LV([[9, 14], [16, 20]]), 6: [9, 14] } }),
      lugar('dra-susana-pedrero', 'Dra. Susana Pedrero de la Cruz', 'Mazatlán, Sin.', '', 'http://www.mydentistsusanapedrero.com/'),
      lugar('unimed-mazatlan', 'Unimed Clínica Dental', 'Mazatlán, Sin.', '', 'https://unimed-1.ueniweb.com/'),
    ],
  },
];
