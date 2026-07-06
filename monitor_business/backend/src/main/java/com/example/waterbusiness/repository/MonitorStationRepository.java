package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.MonitorStation;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface MonitorStationRepository extends JpaRepository<MonitorStation, Long> {

    Optional<MonitorStation> findByStationCode(String stationCode);

    Optional<MonitorStation> findByExternalId(String externalId);
}
