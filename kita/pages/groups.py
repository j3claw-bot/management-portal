import streamlit as st

from models import ChildAttendance, Group, KitaSettings, get_session

AREAS = {"krippe": "Krippe", "elementar": "Elementar"}
WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]


def show_groups(user: dict):
    session = get_session()
    try:
        # --- Kita settings ---
        st.markdown('<div class="section-hdr">Kita-Einstellungen</div>', unsafe_allow_html=True)

        kita = session.query(KitaSettings).first()
        if not kita:
            st.warning("Keine Kita-Einstellungen vorhanden. Bitte Seed-Daten laden.")
            return

        with st.form("kita_settings"):
            kita_name = st.text_input("Name der Kita", value=kita.name)

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                open_time = st.text_input("Öffnung", value=kita.open_time)
            with c2:
                close_time = st.text_input("Schließung", value=kita.close_time)
            with c3:
                core_start = st.text_input("Kernzeit Beginn", value=kita.core_start)
            with c4:
                core_end = st.text_input("Kernzeit Ende", value=kita.core_end)

            if st.form_submit_button("Speichern", use_container_width=True):
                kita.name = kita_name.strip()
                kita.open_time = open_time.strip()
                kita.close_time = close_time.strip()
                kita.core_start = core_start.strip()
                kita.core_end = core_end.strip()
                session.commit()
                st.success("Kita-Einstellungen gespeichert.")
                st.rerun()

        # --- Group list ---
        st.markdown('<div class="section-hdr">Gruppen</div>', unsafe_allow_html=True)

        groups = session.query(Group).order_by(Group.area, Group.name).all()

        if groups:
            rows = []
            for g in groups:
                rows.append({
                    "ID": g.id,
                    "Name": g.name,
                    "Bereich": AREAS.get(g.area, g.area),
                    "Kinder (min)": g.min_children,
                    "Kinder (max)": g.max_children,
                    "Betreuungsschlüssel": f"{g.ratio_num}:{g.ratio_den}",
                    "Aktiv": "Ja" if g.is_active else "Nein",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

        # --- Create group ---
        st.markdown('<div class="section-hdr">Neue Gruppe anlegen</div>', unsafe_allow_html=True)

        with st.form("create_group", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                new_name = st.text_input("Gruppenname")
                new_area = st.selectbox("Bereich", list(AREAS.keys()),
                                        format_func=lambda k: AREAS[k])
                new_min = st.number_input("Min. Kinder", min_value=0, max_value=30, value=6)
            with c2:
                new_max = st.number_input("Max. Kinder", min_value=1, max_value=30, value=12)
                new_ratio_num = st.number_input("Schlüssel (Personal)", min_value=1, max_value=5, value=1)
                new_ratio_den = st.number_input("Schlüssel (Kinder)", min_value=1, max_value=15,
                                                value=4 if new_area == "krippe" else 10)

            if st.form_submit_button("Anlegen", use_container_width=True):
                if not new_name:
                    st.error("Gruppenname ist ein Pflichtfeld.")
                else:
                    g = Group(
                        name=new_name.strip(),
                        area=new_area,
                        min_children=new_min,
                        max_children=new_max,
                        ratio_num=new_ratio_num,
                        ratio_den=new_ratio_den,
                    )
                    session.add(g)
                    session.flush()
                    # Create default attendance for Mon-Fri
                    default_count = new_max - 2
                    for day in range(5):
                        session.add(ChildAttendance(
                            group_id=g.id,
                            weekday=day,
                            expected_children=default_count,
                            arrival_time=kita.open_time,
                            departure_time=kita.close_time,
                        ))
                    session.commit()
                    st.success(f"Gruppe '{g.name}' wurde angelegt.")
                    st.rerun()

        # --- Edit group ---
        if groups:
            st.markdown('<div class="section-hdr">Gruppe bearbeiten</div>', unsafe_allow_html=True)

            grp_options = {g.id: f"{g.name} ({AREAS.get(g.area, g.area)})" for g in groups}
            selected_id = st.selectbox(
                "Gruppe auswählen",
                list(grp_options.keys()),
                format_func=lambda k: grp_options[k],
                key="edit_grp_select",
            )

            grp = session.query(Group).get(selected_id)
            if grp:
                with st.form("edit_group"):
                    c1, c2 = st.columns(2)
                    with c1:
                        edit_name = st.text_input("Gruppenname", value=grp.name)
                        edit_area = st.selectbox(
                            "Bereich", list(AREAS.keys()),
                            index=list(AREAS.keys()).index(grp.area),
                            format_func=lambda k: AREAS[k],
                        )
                        edit_min = st.number_input("Min. Kinder", min_value=0, max_value=30,
                                                   value=grp.min_children)
                    with c2:
                        edit_max = st.number_input("Max. Kinder", min_value=1, max_value=30,
                                                   value=grp.max_children)
                        edit_rn = st.number_input("Schlüssel (Personal)", min_value=1, max_value=5,
                                                  value=grp.ratio_num)
                        edit_rd = st.number_input("Schlüssel (Kinder)", min_value=1, max_value=15,
                                                  value=grp.ratio_den)

                    edit_active = st.checkbox("Aktiv", value=grp.is_active)

                    if st.form_submit_button("Speichern", use_container_width=True):
                        grp.name = edit_name.strip()
                        grp.area = edit_area
                        grp.min_children = edit_min
                        grp.max_children = edit_max
                        grp.ratio_num = edit_rn
                        grp.ratio_den = edit_rd
                        grp.is_active = edit_active
                        session.commit()
                        st.success(f"Gruppe '{grp.name}' wurde aktualisiert.")
                        st.rerun()

                # --- Child attendance per weekday ---
                st.markdown(
                    f'<div class="section-hdr">Kinderzahlen — {grp.name}</div>',
                    unsafe_allow_html=True,
                )

                attendances = (
                    session.query(ChildAttendance)
                    .filter_by(group_id=grp.id)
                    .order_by(ChildAttendance.weekday)
                    .all()
                )

                # Ensure we have records for all 5 days
                existing_days = {a.weekday for a in attendances}
                for day in range(5):
                    if day not in existing_days:
                        att = ChildAttendance(
                            group_id=grp.id,
                            weekday=day,
                            expected_children=grp.max_children - 2,
                            arrival_time=kita.open_time,
                            departure_time=kita.close_time,
                        )
                        session.add(att)
                        attendances.append(att)
                session.flush()
                attendances.sort(key=lambda a: a.weekday)

                with st.form("edit_attendance"):
                    cols = st.columns(5)
                    new_values = []
                    for i, att in enumerate(attendances):
                        with cols[i]:
                            st.caption(WEEKDAYS_DE[att.weekday])
                            count = st.number_input(
                                "Kinder",
                                min_value=0,
                                max_value=grp.max_children,
                                value=att.expected_children,
                                key=f"att_{grp.id}_{att.weekday}",
                            )
                            new_values.append((att, count))

                    if st.form_submit_button("Kinderzahlen speichern", use_container_width=True):
                        for att, count in new_values:
                            att.expected_children = count
                        session.commit()
                        st.success("Kinderzahlen aktualisiert.")
                        st.rerun()
    finally:
        session.close()
