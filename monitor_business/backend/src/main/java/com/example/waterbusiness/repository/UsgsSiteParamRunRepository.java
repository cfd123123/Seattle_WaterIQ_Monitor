package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.UsgsSiteParamRun;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;

public interface UsgsSiteParamRunRepository extends JpaRepository<UsgsSiteParamRun, Long> {

    long countByCreatedAtGreaterThanEqualAndCreatedAtLessThan(LocalDateTime from, LocalDateTime toExclusive);

    List<UsgsSiteParamRun> findByCreatedAtGreaterThanEqualAndCreatedAtLessThan(
            LocalDateTime from,
            LocalDateTime toExclusive
    );

    List<UsgsSiteParamRun> findByStationIdAndCreatedAtGreaterThanEqualAndCreatedAtLessThan(
            Long stationId,
            LocalDateTime from,
            LocalDateTime toExclusive
    );
}
