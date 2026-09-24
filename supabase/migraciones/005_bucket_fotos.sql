-- 005 · El bucket donde se archivan las fotos.
--
-- Privado a proposito: las fotos muestran trabajadores, matriculas y detalles
-- de las fincas. En la base solo queda la ruta, y el enlace para verlas se
-- firma en el momento con vencimiento (storage_service.url_firmada).
--
-- Storage tiene cuota aparte de la base: 1 GB contra 500 MB en el plan
-- gratuito, asi que las fotos no compiten con las tablas por espacio. Aun asi
-- se llena: a ~258 KB por foto y ~100 fotos al dia, en unos 40 dias.
--
-- El nombre tiene que coincidir con SUPABASE_BUCKET_FOTOS del .env.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'fotos-monitoreo',
    'fotos-monitoreo',
    false,
    5242880,  -- 5 MB; una foto de WhatsApp rara vez pasa de 2
    array['image/jpeg', 'image/png', 'image/gif', 'image/webp']
)
on conflict (id) do nothing;
