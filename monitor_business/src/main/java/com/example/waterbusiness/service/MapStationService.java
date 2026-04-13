package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.MapStationPointResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * Map markers: station geometry + latest alert-derived snapshot (USGS-era; no legacy 11-param checks).
 */
@Service
@RequiredArgsConstructor
public class MapStationService {

    private final MonitorStationRepository monitorStationRepository;
    private final AlertEventRepository alertEventRepository;

    public List<MapStationPointResponse> listMapStations() {
        List<MonitorStation> stations = monitorStationRepository.findAll();
        List<MapStationPointResponse> result = new ArrayList<>(stations.size());
        for (MonitorStation station : stations) {
            Optional<AlertEvent> latest =
                    alertEventRepository.findFirstByStationIdOrderByCreatedAtDesc(station.getId());
            long openAlertCount = alertEventRepository.countByStationIdAndStatusIn(
                    station.getId(),
                    List.of("NEW", "ACK")
            );
            result.add(MapStationPointResponse.builder()
                    .stationId(station.getId())
                    .stationCode(station.getStationCode())
                    .stationName(station.getStationName())
                    .province(station.getProvince())
                    .city(station.getCity())
                    .latitude(station.getLatitude())
                    .longitude(station.getLongitude())
                    .externalId(station.getExternalId())
                    .latestPollutionLevel(latest.map(AlertEvent::getPollutionLevel).orElse(null))
                    .latestSampleTime(null)
                    .latestCreateTime(latest.map(AlertEvent::getCreatedAt).orElse(null))
                    .openAlertCount(openAlertCount)
                    .build());
        }
        return result;
    }
}
