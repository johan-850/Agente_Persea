-- 006 · Lo que espera a la mañana.
--
-- El 29 de septiembre a la 1:55 de la mañana le llego a un administrador la
-- respuesta a una pregunta de seis dias antes. De noche el agente ya no le
-- escribe a nadie por su cuenta: las alertas quedan en envios con lo que habia
-- que mandar, y salen cuando termina la noche (ver app/horario.py).
--
-- Estados nuevos: aplazado -> enviando -> aceptado (o fallido), y de ahi los
-- acuses de siempre. Solo las filas aplazadas llevan contenido: las
-- plantillas candidatas con sus parametros y el texto de respaldo.

alter table envios add column if not exists contenido jsonb;
