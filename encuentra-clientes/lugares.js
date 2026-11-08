// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Una respuesta por zona, igual que "Arma las búsquedas" -> "Busca en Google Maps".
// Calificaciones: de agregadores (no de Google). Reseñas: no se obtuvieron textos, se dejan vacías (no se inventan).
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
// h: { 1: [9, 19], ..., 6: [10, 14] }  (0 = domingo)
const horario = (h) => {
  if (!h) return undefined;
  const periods = Object.entries(h).map(([d, [a, c]]) => ({ open: { day: +d, hour: a, minute: 0 }, close: { day: +d, hour: c, minute: 0 } }));
  const orden = [1, 2, 3, 4, 5, 6, 0];
  const weekdayDescriptions = orden.map((d) => `${DIAS[d]}: ${h[d] ? `${h[d][0]}:00–${h[d][1]}:00` : 'Cerrado'}`);
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

module.exports = [
  {
    textQuery: 'dentista en Providencia, Guadalajara, Jalisco',
    places: [
      lugar('odontologia-esp-providencia', 'Odontología Especializada Providencia', 'Av. Manuel Acuña 2942, Providencia, Guadalajara, Jal.', '', ''),
      lugar('providental', 'Providental Ortodoncia e Implantes', 'Av. Providencia 2854, Providencia, Guadalajara, Jal.', '+52 33 1230 8217', ''),
      lugar('cabdental-providencia', 'Cabdental Providencia', 'Av. Terranova 563, Providencia, Guadalajara, Jal.', '+52 33 3640 6313', 'https://cabdental.com/dentista-en-providencia-guadalajara/'),
      lugar('dentalia-guadalajara', 'Dentalia Guadalajara', 'Valparaíso 2367, Providencia, Guadalajara, Jal.', '+52 33 3817 1929', 'https://www.dentalia.com/'),
      lugar('dhic-providencia', 'DHIC Dental Health & Implant Center (Providencia)', 'Providencia, Guadalajara, Jal.', '', '', { rating: 4.5, total: 28 }),
      lugar('takahashi', 'Dr. Carlos Taitó Takahashi Aguilar', 'Loma de Providencia, Guadalajara, Jal.', '', ''),
      lugar('brenda-sanchez', 'Dra. Brenda Sánchez García', 'Guadalajara, Jal.', '', 'https://www.doctoralia.com.mx/perfil/brenda-sanchez-garcia', { total: 38 }),
    ],
  },
  {
    textQuery: 'dentista en Chapultepec, Guadalajara, Jalisco',
    places: [
      lugar('kiyodent-chapultepec', 'Kiyodent Dental Clinic Chapultepec', 'C. Colonias 691-L 1, Moderna, 44190 Guadalajara, Jal.', '+52 33 2810 9300', '', { h: semana(9, 19, [10, 19]) }),
      lugar('une-chapultepec', 'Dental Clinic UNE', 'Av. Chapultepec Sur 734, Guadalajara, Jal.', '+52 33 8000 0825', ''),
      lugar('odontologia-moderna', 'Odontología Moderna', 'C. Manuel López Cotilla 1481B, Zona Chapultepec, Guadalajara, Jal.', '+52 33 1705 5871', 'https://dentistaenguadalajara.com/contacto/'),
      lugar('dental-paz', 'Consultorio Dental Americana (Dental Paz)', 'Av. de la Paz 1699, Americana, Guadalajara, Jal.', '+52 33 1359 6262', ''),
      lugar('mejorada-huerta', 'Dra. Leticia del Rayo Mejorada Huerta', 'C. José María Morelos 1863, Lafayette, Guadalajara, Jal.', '+52 33 3615 6182', ''),
      lugar('clinica-dental-americana', 'Clínica Dental Americana', 'Prolongación Américas 2145, Guadalajara, Jal.', '+52 33 3636 2602', ''),
      lugar('dentimex-lafayette', 'Dentimex Lafayette', 'Chapultepec Norte 83, Lafayette, Guadalajara, Jal.', '+52 800 901 3888', ''),
      lugar('dento-metric', 'Dento Metric', 'Chapultepec Country, Guadalajara, Jal.', '+52 33 3817 1448', ''),
    ],
  },
  {
    textQuery: 'dentista en Zapopan Centro, Guadalajara, Jalisco',
    places: [
      lugar('mf-dental-center', 'MF Dental Center', '28 de Enero 93, planta alta, Zapopan Centro, Zapopan, Jal.', '+52 33 1071 9742', 'https://mfdentalcenter.com/', { rating: 5, total: 241, h: semana(10, 19, [10, 14]) }),
      lugar('la-zapopana-matriz', 'Clínica Dental La Zapopana (Matriz Zapopan)', 'Emiliano Zapata 80, Zapopan Centro, Zapopan, Jal.', '+52 33 3633 7369', 'https://www.dentallazapopana.com/', { h: semana(8, 20, [8, 20], [8, 20]) }),
      lugar('vibliorio', 'Dentist Vibliorio', 'Zapopan, Jal.', '+52 33 3656 1823', 'https://www.dentistvibliorio.com.mx/', { h: semana(10, 20, [10, 14]) }),
      lugar('clinica-dental-zapopan', 'La Clínica Dental Zapopan', 'Zapopan, Jal.', '+52 33 1580 9893', 'https://dentalguadalajara.com.mx/zapopan/', { h: semana(9, 20, [9, 16]) }),
      lugar('lomas-de-zapopan', 'Dentista Lomas de Zapopan', 'Av. de la Mancha 798, local 8, Zapopan, Jal.', '+52 33 1699 5436', 'https://www.facebook.com/p/Dentista-Lomas-De-Zapopan-100063626723331/'),
      lugar('dentalia-real-center', 'Dentalia Real Center', 'Santa Margarita, Zapopan, Jal.', '+52 800 003 3682', 'https://www.dentalia.com/dentistas/zapopan', { rating: 4.4, total: 211 }),
    ],
  },
];
