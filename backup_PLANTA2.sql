--
-- PostgreSQL database dump
--

\restrict oD1yRljTTx8Iigyn7vxfCA71rIiNtHOQdNldBca6dg4J1YHCvf47sMxoypNPvD8

-- Dumped from database version 14.20 (Debian 14.20-1.pgdg12+1)
-- Dumped by pg_dump version 14.20 (Debian 14.20-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: historial_cambios; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.historial_cambios (
    id integer NOT NULL,
    entidad character varying(255) NOT NULL,
    entidad_id character varying(255) NOT NULL,
    campo_modificado character varying(255) NOT NULL,
    valor_anterior text,
    valor_nuevo text,
    modificado_por character varying(255),
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.historial_cambios OWNER TO postgres;

--
-- Name: historial_cambios_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.historial_cambios_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.historial_cambios_id_seq OWNER TO postgres;

--
-- Name: historial_cambios_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.historial_cambios_id_seq OWNED BY public.historial_cambios.id;


--
-- Name: logs_busqueda; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.logs_busqueda (
    clave integer NOT NULL,
    maquina_id_filtro character varying(255),
    uso_en_filtro text,
    resultado_top_1_clave character varying(255),
    distancia_top_1 real,
    imagen_busqueda_path text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.logs_busqueda OWNER TO postgres;

--
-- Name: logs_busqueda_clave_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.logs_busqueda_clave_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.logs_busqueda_clave_seq OWNER TO postgres;

--
-- Name: logs_busqueda_clave_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.logs_busqueda_clave_seq OWNED BY public.logs_busqueda.clave;


--
-- Name: maquinas; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.maquinas (
    clave character varying(50) NOT NULL,
    nombre text NOT NULL,
    descripcion text,
    ubicacion text,
    uso_en text,
    proveedores text,
    imagen text,
    tiene_foto boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    updated_by character varying(255),
    is_deleted boolean DEFAULT false
);


ALTER TABLE public.maquinas OWNER TO postgres;

--
-- Name: piezas; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.piezas (
    clave character varying(255) NOT NULL,
    maquina_id character varying(50) NOT NULL,
    nombre text NOT NULL,
    imagen text NOT NULL,
    ubicacion text,
    uso_en text,
    proveedores text,
    tiene_foto boolean DEFAULT false,
    imagen_2 text,
    imagen_3 text,
    embedding public.vector(1536),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    updated_by character varying(255),
    is_deleted boolean DEFAULT false
);


ALTER TABLE public.piezas OWNER TO postgres;

--
-- Name: piezas_clave_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.piezas_clave_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.piezas_clave_seq OWNER TO postgres;

--
-- Name: piezas_clave_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.piezas_clave_seq OWNED BY public.piezas.clave;


--
-- Name: historial_cambios id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.historial_cambios ALTER COLUMN id SET DEFAULT nextval('public.historial_cambios_id_seq'::regclass);


--
-- Name: logs_busqueda clave; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.logs_busqueda ALTER COLUMN clave SET DEFAULT nextval('public.logs_busqueda_clave_seq'::regclass);


--
-- Name: piezas clave; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.piezas ALTER COLUMN clave SET DEFAULT nextval('public.piezas_clave_seq'::regclass);


--
-- Data for Name: historial_cambios; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.historial_cambios (id, entidad, entidad_id, campo_modificado, valor_anterior, valor_nuevo, modificado_por, created_at) FROM stdin;
\.


--
-- Data for Name: logs_busqueda; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.logs_busqueda (clave, maquina_id_filtro, uso_en_filtro, resultado_top_1_clave, distancia_top_1, imagen_busqueda_path, created_at) FROM stdin;
\.


--
-- Data for Name: maquinas; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.maquinas (clave, nombre, descripcion, ubicacion, uso_en, proveedores, imagen, tiene_foto, created_at, updated_at, updated_by, is_deleted) FROM stdin;
\.


--
-- Data for Name: piezas; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.piezas (clave, maquina_id, nombre, imagen, ubicacion, uso_en, proveedores, tiene_foto, imagen_2, imagen_3, embedding, created_at, updated_at, updated_by, is_deleted) FROM stdin;
\.


--
-- Name: historial_cambios_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.historial_cambios_id_seq', 1, false);


--
-- Name: logs_busqueda_clave_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.logs_busqueda_clave_seq', 1, false);


--
-- Name: piezas_clave_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.piezas_clave_seq', 1, false);


--
-- Name: historial_cambios historial_cambios_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.historial_cambios
    ADD CONSTRAINT historial_cambios_pkey PRIMARY KEY (id);


--
-- Name: logs_busqueda logs_busqueda_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.logs_busqueda
    ADD CONSTRAINT logs_busqueda_pkey PRIMARY KEY (clave);


--
-- Name: maquinas maquinas_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.maquinas
    ADD CONSTRAINT maquinas_pkey PRIMARY KEY (clave);


--
-- Name: piezas piezas_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.piezas
    ADD CONSTRAINT piezas_pkey PRIMARY KEY (clave);


--
-- Name: idx_piezas_embedding_hnsw; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_piezas_embedding_hnsw ON public.piezas USING hnsw (embedding public.vector_l2_ops) WITH (m='16', ef_construction='64');


--
-- Name: logs_busqueda logs_busqueda_resultado_top_1_clave_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.logs_busqueda
    ADD CONSTRAINT logs_busqueda_resultado_top_1_clave_fkey FOREIGN KEY (resultado_top_1_clave) REFERENCES public.piezas(clave);


--
-- PostgreSQL database dump complete
--

\unrestrict oD1yRljTTx8Iigyn7vxfCA71rIiNtHOQdNldBca6dg4J1YHCvf47sMxoypNPvD8

